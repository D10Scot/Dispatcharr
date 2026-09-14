package ffmpeg

import (
	"regexp"
	"strconv"
	"strings"
)

// Progress is what one ffmpeg progress record ("frame=  150 fps=0.0 ...
// speed=11.5x") says, the four values input/manager.py:1102-1135's
// _parse_ffmpeg_stats extracts. A nil pointer is a field the line did not
// carry.
type Progress struct {
	// Speed is the cumulative playback-to-wall-clock ratio ffmpeg reports.
	Speed *float64
	// FPS is ffmpeg's own output frame rate.
	FPS *float64
	// ActualFPS is FPS / Speed when both are present and Speed is positive.
	ActualFPS *float64
	// OutputBitrateKbps is the output bitrate in kbit/s, with an 'm' or 'g'
	// unit scaled up.
	OutputBitrateKbps *float64
}

// The three regexes, input/manager.py:1109, :1113 and :1117, verbatim.
//
// speedRe STOPS AT THE 'e' OF SCIENTIFIC NOTATION, and that is parity-matrix
// row 28 (issue #227): real ffmpeg emits "speed=1.41e+03x" on a truncated
// input and both status surfaces then report 1.41, a thousandfold
// under-report. Spec D5 is strict parity, defects included; do not widen the
// character class without changing the Python side and the row together.
var (
	speedRe   = regexp.MustCompile(`speed=\s*([0-9.]+)x?`)
	fpsRe     = regexp.MustCompile(`fps=\s*([0-9.]+)`)
	bitrateRe = regexp.MustCompile(`(?i)bitrate=\s*([0-9.]+(?:\.[0-9]+)?)\s*([kmg]?)bits/s`)
)

// IsProgressLine is the gate input/manager.py:993 and :1017 apply before
// calling _parse_ffmpeg_stats: the substring "frame=" anywhere in the line.
func IsProgressLine(line string) bool { return strings.Contains(line, "frame=") }

// ParseProgress extracts the four values from a progress record.
//
// It returns false when the line carries none of them, AND when a captured
// number does not parse: `[0-9.]+` happily captures "1.2.3", Python's float()
// then raises, and the except at input/manager.py:1249 swallows the WHOLE
// line -- no stats update, no buffering check. A Go port that parsed the
// fields it could and skipped the one it could not would arm the buffering
// detector on a line Python ignores.
func ParseProgress(line string) (Progress, bool) {
	var p Progress
	if m := speedRe.FindStringSubmatch(line); m != nil {
		v, err := strconv.ParseFloat(m[1], 64)
		if err != nil {
			return Progress{}, false
		}
		p.Speed = &v
	}
	if m := fpsRe.FindStringSubmatch(line); m != nil {
		v, err := strconv.ParseFloat(m[1], 64)
		if err != nil {
			return Progress{}, false
		}
		p.FPS = &v
	}
	if m := bitrateRe.FindStringSubmatch(line); m != nil {
		v, err := strconv.ParseFloat(m[1], 64)
		if err != nil {
			return Progress{}, false
		}
		switch strings.ToLower(m[2]) {
		case "m":
			v *= 1000
		case "g":
			v *= 1_000_000
		}
		p.OutputBitrateKbps = &v
	}
	if p.FPS != nil && p.Speed != nil && *p.Speed > 0 {
		actual := *p.FPS / *p.Speed
		p.ActualFPS = &actual
	}
	if p.Speed == nil && p.FPS == nil && p.OutputBitrateKbps == nil {
		return Progress{}, false
	}
	return p, true
}

// Round rounds to `places` decimal places the way Python's round() does on a
// float: on the exact decimal expansion of the binary value, ties to even.
// strconv's 'f' formatting is correctly rounded on the same expansion, so
// formatting and parsing back gives the same double Python's round() gives,
// where math.Round(x*1000)/1000 can differ by one unit in the last place on
// a value like 0.0005 whose binary form is not what it looks like.
//
// It exists because the Python relay stores every stat as str(round(x, n))
// (input/manager.py:1260-1269, channel_service.py:858-880) and the status
// endpoints read that string back as a float, so the value on the wire is
// the rounded one.
func Round(x float64, places int) float64 {
	v, err := strconv.ParseFloat(strconv.FormatFloat(x, 'f', places, 64), 64)
	if err != nil {
		return x
	}
	return v
}
