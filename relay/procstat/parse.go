package procstat

import (
	"encoding/binary"
	"errors"
	"strconv"
	"strings"
)

// ParseStat parses one /proc/<pid>/stat line (proc(5)).
//
// The command name (field 2) is in parentheses and may itself contain spaces
// and parentheses, so the fields after it are found by splitting after the
// LAST ')'.
func ParseStat(line string) (Proc, error) {
	open := strings.IndexByte(line, '(')
	closing := strings.LastIndexByte(line, ')')
	if open < 0 || closing < open {
		return Proc{}, errors.New("procstat: no command name in stat line")
	}
	pid, err := strconv.Atoi(strings.TrimSpace(line[:open]))
	if err != nil {
		return Proc{}, errors.New("procstat: stat line does not start with a pid")
	}
	// rest[0] is field 3 (state), so field n is rest[n-3].
	rest := strings.Fields(line[closing+1:])
	if len(rest) < 22 { // through field 24 (rss)
		return Proc{}, errors.New("procstat: stat line is too short")
	}
	field := func(n int) (uint64, error) { return strconv.ParseUint(rest[n-3], 10, 64) }
	pgrp, err := strconv.Atoi(rest[5-3])
	if err != nil {
		return Proc{}, errors.New("procstat: bad process group")
	}
	utime, err := field(14)
	if err != nil {
		return Proc{}, errors.New("procstat: bad utime")
	}
	stime, err := field(15)
	if err != nil {
		return Proc{}, errors.New("procstat: bad stime")
	}
	start, err := field(22)
	if err != nil {
		return Proc{}, errors.New("procstat: bad starttime")
	}
	rss, err := strconv.ParseInt(rest[24-3], 10, 64)
	if err != nil {
		return Proc{}, errors.New("procstat: bad rss")
	}
	return Proc{PID: pid, PGrp: pgrp, Start: start, CPUTicks: utime + stime, RSSPages: rss}, nil
}

const (
	atClktck       = 17
	defaultClkTick = 100
)

// ParseAuxv returns AT_CLKTCK from the contents of /proc/self/auxv: pairs of
// native-word integers, type then value. It returns 100 when the entry is
// absent or the buffer is malformed, which is what Linux uses on every
// architecture the relay is built for.
func ParseAuxv(b []byte, wordSize int, order binary.ByteOrder) int {
	if wordSize != 4 && wordSize != 8 {
		return defaultClkTick
	}
	read := func(p []byte) uint64 {
		if wordSize == 4 {
			return uint64(order.Uint32(p))
		}
		return order.Uint64(p)
	}
	for len(b) >= 2*wordSize {
		typ, val := read(b[:wordSize]), read(b[wordSize:2*wordSize])
		b = b[2*wordSize:]
		if typ == 0 { // AT_NULL
			break
		}
		if typ == atClktck && val > 0 && val < 1<<20 {
			return int(val)
		}
	}
	return defaultClkTick
}
