package hls

import (
	"encoding/binary"
	"errors"
	"io"
)

// readSize is how much the reader asks each pipe for at once, relay/output's
// figure.
const readSize = 65536

// maxInitBytes bounds the boxes held before the moov, relay/output's figure
// for the same init segment.
const maxInitBytes = 10 << 20

// errNoInit is an output that wrote a fragment before any init segment.
var errNoInit = errors.New("hls: an encoder output wrote a moof before its moov")

// splitter cuts one encoder output's byte stream into its init segment and
// its fragments, as the bytes arrive (spec D6). The init segment is every box
// up to and including the moov -- ftyp and moov, which `delay_moov` writes
// only once the first packets are known -- and it is handed on the moment
// the moov is complete, so the multivariant can be answered before the first
// 2 s fragment exists. A fragment is a moof and the mdat after it. Any other
// top-level box after the moov (an mfra at the end of the output, say)
// belongs to neither and is dropped.
type splitter struct {
	buf      []byte
	init     []byte
	haveInit bool
	pending  []byte // a moof waiting for its mdat
	onInit   func([]byte) error
	onFrag   func([]byte) error
}

// read drains r to EOF through the splitter. It returns nil at a clean EOF,
// even one that cut a box short: a generation's flushed tail is complete, and
// a process that died mid-fragment has already said so through its exit
// status, so a partial box is simply not a fragment.
func (s *splitter) read(r io.Reader) error {
	chunk := make([]byte, readSize)
	for {
		n, err := r.Read(chunk)
		if n > 0 {
			s.buf = append(s.buf, chunk[:n]...)
			if perr := s.drain(); perr != nil {
				return perr
			}
		}
		if err != nil {
			if errors.Is(err, io.EOF) {
				return nil
			}
			return err
		}
	}
}

// drain takes every whole box off the front of the buffer.
func (s *splitter) drain() error {
	for len(s.buf) >= 8 {
		declared := declaredSize(s.buf)
		largesize := binary.BigEndian.Uint32(s.buf) == 1
		switch {
		case declared > maxBoxBytes:
			return boxErr("a %q box declares more than %d bytes", string(s.buf[4:8]), maxBoxBytes)
		case declared < 0:
			return nil // a 64-bit size not yet complete
		case declared < 8 || (largesize && declared < 16):
			return boxErr("a %q box declares %d bytes, less than its own header", string(s.buf[4:8]), declared)
		case declared > int64(len(s.buf)):
			return nil // the rest of the box has not arrived yet
		}
		size := int(declared)
		typ := string(s.buf[4:8])
		b := s.buf[:size:size]
		s.buf = append([]byte(nil), s.buf[size:]...)
		if err := s.box(typ, b); err != nil {
			return err
		}
	}
	return nil
}

// declaredSize is the size a box header claims, whether or not the box has
// arrived yet: -1 while a 64-bit size is itself incomplete, and past
// maxBoxBytes for a size of 0 ("to the end of the file", which on a pipe is
// a box that never ends) or anything else too large to hold.
func declaredSize(b []byte) int64 {
	size := int64(binary.BigEndian.Uint32(b))
	switch size {
	case 0:
		return maxBoxBytes + 1
	case 1:
		if len(b) < 16 {
			return -1
		}
		large := binary.BigEndian.Uint64(b[8:16])
		if large > maxBoxBytes {
			return maxBoxBytes + 1
		}
		return int64(large)
	}
	return size
}

func (s *splitter) box(typ string, b []byte) error {
	if !s.haveInit {
		if typ == "moof" {
			return errNoInit
		}
		s.init = append(s.init, b...)
		if len(s.init) > maxInitBytes {
			return boxErr("no moov in the first %d bytes of an encoder output", maxInitBytes)
		}
		if typ != "moov" {
			return nil
		}
		s.haveInit = true
		init := s.init
		s.init = nil
		return s.onInit(init)
	}
	switch typ {
	case "moof":
		s.pending = b
	case "mdat":
		if s.pending == nil {
			return nil
		}
		frag := make([]byte, 0, len(s.pending)+len(b))
		frag = append(append(frag, s.pending...), b...)
		s.pending = nil
		return s.onFrag(frag)
	}
	return nil
}
