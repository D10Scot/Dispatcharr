package procstat

import (
	"encoding/binary"
	"strconv"
	"strings"
	"testing"
)

// A stat line whose command name holds spaces AND parentheses: splitting on
// the first ')' or on whitespace would put every later field in the wrong
// column, so the pgrp, CPU and RSS below would all be wrong.
const awkwardStat = "4242 (my ) (prog (x) ) S 1 777 777 0 -1 4194304 100 0 0 0 " +
	"30 12 0 0 20 0 1 0 987654 1048576 321 18446744073709551615 0 0 0 0 0 0 0 0 0"

func TestParseStatSurvivesParenthesesInTheName(t *testing.T) {
	p, err := ParseStat(awkwardStat)
	if err != nil {
		t.Fatal(err)
	}
	want := Proc{PID: 4242, PGrp: 777, Start: 987654, CPUTicks: 42, RSSPages: 321}
	if p != want {
		t.Fatalf("ParseStat = %+v, want %+v", p, want)
	}
}

// statWith builds a stat line whose field n (3-based, as in proc(5)) is v.
func statWith(n int, v string) string {
	fields := make([]string, 0, 30)
	for i := 3; i <= 30; i++ {
		fields = append(fields, strconv.Itoa(i))
	}
	fields[n-3] = v
	return "12 (foo) " + strings.Join(fields, " ")
}

func TestParseStatRejectsMalformedLines(t *testing.T) {
	for name, line := range map[string]string{
		"empty":         "",
		"no parens":     "12 foo S 1 2",
		"short":         "12 (foo) S 1 2 3",
		"not a pid":     "x" + statWith(3, "3")[2:],
		"bad pgrp":      statWith(5, "zz"),
		"bad utime":     statWith(14, "xx"),
		"bad stime":     statWith(15, "yy"),
		"bad starttime": statWith(22, "qq"),
		"bad rss":       statWith(24, "rr"),
	} {
		if _, err := ParseStat(line); err == nil {
			t.Errorf("%s: ParseStat accepted %q", name, line)
		}
	}
}

type order interface {
	binary.ByteOrder
	binary.AppendByteOrder
}

func auxv(order order, word int, pairs ...[2]uint64) []byte {
	var b []byte
	for _, p := range pairs {
		for _, v := range p {
			if word == 8 {
				b = order.AppendUint64(b, v)
			} else {
				b = order.AppendUint32(b, uint32(v))
			}
		}
	}
	return b
}

func TestParseAuxv(t *testing.T) {
	for _, tc := range []struct {
		name  string
		word  int
		order order
		buf   []byte
		want  int
	}{
		{"64-bit little endian", 8, binary.LittleEndian, auxv(binary.LittleEndian, 8, [2]uint64{6, 4096}, [2]uint64{17, 250}, [2]uint64{0, 0}), 250},
		{"32-bit big endian", 4, binary.BigEndian, auxv(binary.BigEndian, 4, [2]uint64{17, 1000}, [2]uint64{0, 0}), 1000},
		{"absent falls back to 100", 8, binary.LittleEndian, auxv(binary.LittleEndian, 8, [2]uint64{6, 4096}, [2]uint64{0, 0}), 100},
		{"nothing after AT_NULL is read", 8, binary.LittleEndian, auxv(binary.LittleEndian, 8, [2]uint64{0, 0}, [2]uint64{17, 250}), 100},
		{"truncated", 8, binary.LittleEndian, []byte{1, 2, 3}, 100},
		{"zero is not a tick rate", 8, binary.LittleEndian, auxv(binary.LittleEndian, 8, [2]uint64{17, 0}), 100},
		{"odd word size", 3, binary.LittleEndian, nil, 100},
	} {
		if got := ParseAuxv(tc.buf, tc.word, tc.order); got != tc.want {
			t.Errorf("%s: ParseAuxv = %d, want %d", tc.name, got, tc.want)
		}
	}
}
