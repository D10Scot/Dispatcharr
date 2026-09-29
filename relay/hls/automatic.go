package hls

import (
	"fmt"
	"strconv"
	"strings"
	"time"
)

// Automatic mode (Phase 4a-1d, spec D12 and § Automatic generation): copy
// what AVPlayer accepts, encode the rest. Every decision here is a pure
// function of a probe, so each is pinned by a table of literals and each
// carries a one-word reason the generation logs.

// The reasons an automatic decision gives for encoding rather than copying
// the video. copyEligible answers the first eight at every generation;
// VideoDecision adds the run's own conditions for a later one.
const (
	reasonFieldOrder       = "field_order"
	reasonCodec            = "codec"
	reasonProfile          = "profile"
	reasonBitDepth         = "bit_depth"
	reasonKeyframes        = "keyframes"
	reasonKeyframeInterval = "keyframe_interval"
	reasonGeometry         = "geometry"
	reasonFrameRate        = "frame_rate"
	reasonFamily           = "family"
	reasonLevel            = "level"
	reasonBitrate          = "bitrate"
	reasonForced           = "forced"
)

// MaxKeyframeInterval is the longest keyframe interval K a copy is made of:
// beyond it the segments would be too long to seek within and the target
// duration too large for the presence thresholds it scales (spec R42).
const MaxKeyframeInterval = 6 * time.Second

// MaxTargetDuration is the longest target duration an automatic run has,
// which is targetFor(MaxKeyframeInterval).
const MaxTargetDuration = 6

// familyLevel is each family's encode level: 4.2 for H.264 (-level 42) and
// 4.1 for HEVC (-level 41, level-idc=4.1), in ffprobe's units.
func familyLevel(f Family) int {
	if f == FamilyHEVC {
		return 123
	}
	return 42
}

// codecFamily is the family a codec_name belongs to, and false for any other.
func codecFamily(codec string) (Family, bool) {
	switch codec {
	case "h264":
		return FamilyH264, true
	case "hevc":
		return FamilyHEVC, true
	}
	return FamilyH264, false
}

// targetFor is the target duration of a copy with keyframe interval k:
// max(2, ceil(k - 0.1 s)). RFC 8216 § 4.3.3.1 rounds EXTINF, so a 2.002 s GOP
// keeps a target of 2 where ceil(k) would give 3 (R61). Integer arithmetic.
func targetFor(k time.Duration) int {
	d := k - 100*time.Millisecond
	seconds := int((d + time.Second - 1) / time.Second)
	return max(2, seconds)
}

// copyEligible is the copy rule of spec § Automatic generation on one probe:
// whether its video may be copied, and if not, the first reason it may not.
// It knows nothing of any run's output, so generation 0's decision is exactly
// this; a later generation's is VideoDecision's.
//
// The order is the reasons' order: the codec and its profile and bit depth,
// then the two observations the window must hold, then geometry and rate,
// which a copy cannot change. HEVC's "Main 10" passes the profile check on
// purpose so a 10-bit stream is reported for what it is, bit_depth.
func copyEligible(p Probe) (ok bool, reason string) {
	v := p.Video
	if v == nil {
		return false, reasonCodec
	}
	if v.Field == FieldInterlaced {
		return false, reasonFieldOrder
	}
	family, known := codecFamily(v.Codec)
	if !known {
		return false, reasonCodec
	}
	if !profileCopyable(family, v.Profile) {
		return false, reasonProfile
	}
	if v.PixFmt != "yuv420p" && v.PixFmt != "yuvj420p" {
		return false, reasonBitDepth
	}
	if p.Keyframes < 2 {
		return false, reasonKeyframes
	}
	if p.KeyframeInterval > MaxKeyframeInterval {
		return false, reasonKeyframeInterval
	}
	if v.Width <= 0 || v.Height <= 0 || v.Width > maxWidth || v.Height > maxHeight {
		return false, reasonGeometry
	}
	if v.FrameRate.Num <= 0 || v.FrameRate.Den <= 0 || v.FrameRate.Num > maxFrameRate*v.FrameRate.Den {
		return false, reasonFrameRate
	}
	return true, ""
}

// profileCopyable is the profiles a copy keeps the declared CODECS true for:
// H.264 Constrained Baseline, Baseline, Main or High, and HEVC Main (whose
// 10-bit sibling "Main 10" is caught by the bit-depth check after it).
func profileCopyable(f Family, profile string) bool {
	if f == FamilyHEVC {
		return profile == "Main" || profile == "Main 10"
	}
	switch profile {
	case "Constrained Baseline", "Baseline", "Main", "High":
		return true
	}
	return false
}

// DecideFor fixes the run's Output from generation 0's probe in a mode. In
// transcode it is Decide with a target of 2 and the table's rates, so the
// multivariant is what it always was. In automatic a copyable video keeps its
// own geometry and rate, declares its own family and level, and sets the
// target duration; anything else is Decide's encode, H.264 at target 2.
func DecideFor(p Probe, mode Mode) (Output, error) {
	out, err := Decide(p)
	if err != nil {
		return Output{}, err
	}
	out.Family, out.Target, out.Level = FamilyH264, 2, familyLevel(FamilyH264)
	out.PeakRate, out.AverageRate = out.VideoMaxrate, out.VideoBitrate
	if mode != ModeAutomatic {
		return out, nil
	}
	out.Automatic = true
	if ok, _ := copyEligible(p); !ok {
		return out, nil
	}
	family, _ := codecFamily(p.Video.Codec)
	out.Family = family
	out.Width, out.Height = p.Video.Width, p.Video.Height
	out.FrameRate = p.Video.FrameRate
	out.Target = targetFor(p.KeyframeInterval)
	out.Level = max(p.Video.Level, familyLevel(family))
	out.PeakRate = max(out.VideoMaxrate, p.BitRate*5/4)
	out.AverageRate = max(out.VideoBitrate, p.BitRate)
	return out, nil
}

// VideoDecision is a later generation's decision, and generation 0's once the
// output exists: copy only when copyEligible says so AND the probe matches the
// run's fixed output (R60, R75) -- its family, geometry, frame rate, level,
// a keyframe interval its target allows, and a rate that fits the bandwidth
// the multivariant already declared. Otherwise the video is encoded into the
// run's family. forceEncode is set after an over-long segment or a failed copy
// and gives (false, "forced") whatever the probe says.
func (o Output) VideoDecision(p Probe, forceEncode bool) (copied bool, reason string) {
	if forceEncode {
		return false, reasonForced
	}
	if ok, why := copyEligible(p); !ok {
		return false, why
	}
	v := p.Video
	if family, _ := codecFamily(v.Codec); family != o.Family {
		return false, reasonFamily
	}
	if v.Width != o.Width || v.Height != o.Height {
		return false, reasonGeometry
	}
	if v.FrameRate.Num*o.FrameRate.Den != o.FrameRate.Num*v.FrameRate.Den {
		return false, reasonFrameRate
	}
	if targetFor(p.KeyframeInterval) > o.Target {
		return false, reasonKeyframeInterval
	}
	if v.Level > o.Level {
		return false, reasonLevel
	}
	if p.BitRate*5/4 > max(o.VideoMaxrate, o.PeakRate) || p.BitRate > max(o.VideoBitrate, o.AverageRate) {
		return false, reasonBitrate
	}
	return true, ""
}

// PlanAutomatic is PlanGeneration for an automatic run: the video is copied
// or encoded by VideoDecision, and the aac rendition is copied when the first
// qualifying stream is AAC-LC stereo. ac3 and eac3 are filled as in
// transcode. The generation number is for the caller's logging; the plan is a
// function of the probe alone.
func PlanAutomatic(o Output, p Probe, engine Engine, _ int, forceEncode bool) Plan {
	plan := PlanGeneration(o, p, engine)
	plan.Family = o.Family
	if copying, _ := o.VideoDecision(p, forceEncode); copying {
		plan.VideoCopy, plan.Engine, plan.Deinterlace = true, EngineCopy, false
	}
	if fill, ok := plan.Fills[RenditionAAC]; ok && fill.Kind == FillEncode {
		if src := fill.Source; src.Codec == "aac" && src.Profile == "LC" && src.Channels == 2 {
			plan.Fills[RenditionAAC] = Fill{Kind: FillCopy, Source: src}
		}
	}
	return plan
}

// declaredVideoCodec is the multivariant's video CODECS for an automatic run:
// the first complete generation's own string raised to the family's ceiling
// (spec, "The multivariant in automatic mode"), so every generation of the
// run, copied or encoded, is decodable at what was declared. An H.264 string
// becomes High at the higher of its level and the declared one, and an HEVC
// string keeps every field but its level. A string it cannot read is returned
// as it is.
func declaredVideoCodec(codec string, o Output) string {
	declared, _ := ceilingCodec(codec, o)
	return declared
}

// ceilingCodec is declaredVideoCodec with whether the string was one it
// could read.
func ceilingCodec(codec string, o Output) (string, bool) {
	switch {
	case strings.HasPrefix(codec, "avc1.") && len(codec) == len("avc1.")+6:
		level, err := strconv.ParseUint(codec[len(codec)-2:], 16, 8)
		if err != nil {
			return codec, false
		}
		return fmt.Sprintf("avc1.6400%02x", max(int(level), o.Level)), true
	case strings.HasPrefix(codec, "hvc1."):
		fields := strings.Split(codec, ".")
		if len(fields) < 4 || len(fields[3]) < 2 || (fields[3][0] != 'L' && fields[3][0] != 'H') {
			return codec, false
		}
		level, err := strconv.Atoi(fields[3][1:])
		if err != nil {
			return codec, false
		}
		fields[3] = fields[3][:1] + strconv.Itoa(max(level, o.Level))
		return strings.Join(fields, "."), true
	}
	return codec, false
}
