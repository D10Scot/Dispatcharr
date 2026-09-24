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

// The three regexes. fpsRe and bitrateRe are input/manager.py:1113 and :1117
// verbatim.
//
// speedRe READS AN EXPONENT, and that is parity-matrix row 28 (issue #227,
// fixed): real ffmpeg emits "speed=1.41e+03x" on a truncated input, and the
// Python relay's `[0-9.]+` (input/manager.py:1109) stopped at the 'e' and
// reported 1.41, a thousandfold under-report on both status surfaces.
// fpsRe keeps the narrow class: ffmpeg is not observed to print a frame rate
// in scientific notation, and a speculative widening is a change with no
// capture behind it.
var (
	speedRe   = regexp.MustCompile(`speed=\s*([0-9.]+(?:[eE][-+]?[0-9]+)?)x?`)
	fpsRe     = regexp.MustCompile(`fps=\s*([0-9.]+)`)
	bitrateRe = regexp.MustCompile(`(?i)bitrate=\s*([0-9.]+(?:\.[0-9]+)?)\s*([kmg]?)bits/s`)
)

// IsProgressLine is the gate in front of ParseProgress.
//
// input/manager.py:993 and :1017 required the substring "frame=", and that
// is blind on ffmpeg 6.x (issue #299): a stream-copy progress record there
// begins "size=" and carries no frame= at all
// ("size=      19kB time=00:00:01.06 bitrate= 148.5kbits/s speed=2.01x"),
// so no speed was ever recorded and the buffering detector could never arm.
// 7.1, 8.1.2 (the shipped ffmpeg) and 9.0 lead with frame= and pass the first
// clause; ffmpeg 6.x passes the second. Lines arrive trimmed (emit), so the
// prefix test sees the record's first token.
func IsProgressLine(line string) bool {
	if strings.Contains(line, "frame=") {
		return true
	}
	return (strings.HasPrefix(line, "size=") || strings.HasPrefix(line, "Lsize=")) && strings.Contains(line, "speed=")
}

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
