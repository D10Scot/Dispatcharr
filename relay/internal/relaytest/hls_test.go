package relaytest

import "testing"

// --fd-file takes N=PATH for fd 1 or fd 3 and up; fd 0 is the relay's input
// and fd 2 its stderr reader, and a malformed value is a parse failure the
// stand-in reports rather than a flag it silently ignores.
func TestFDFileArgsParse(t *testing.T) {
	if f, ok := parseFDFile(FDFileArg(4, "/tmp/a.mp4")); !ok || f.fd != 4 || f.path != "/tmp/a.mp4" {
		t.Fatalf("FDFileArg(4, ...) parses as %+v, %t", f, ok)
	}
	for _, bad := range []string{"0=/x", "2=/x", "-1=/x", "x=/x", "3=", "3"} {
		if _, ok := parseFDFile(bad); ok {
			t.Errorf("--fd-file %q was accepted", bad)
		}
	}
	o := parseStandIn([]string{"--fd-file", "7"})
	if o.fatalParseFlag != "--fd-file" {
		t.Errorf("a malformed --fd-file did not fail the parse: %+v", o.fatalParseFlag)
	}
	o = parseStandIn([]string{"--fd-file", "1=/p", "--fd-file", "3=/a", "--wait-stdin-eof", "--ignore-stdin-eof"})
	if len(o.fdFiles) != 2 || !o.waitStdinEOF || !o.ignoreStdinEOF {
		t.Errorf("the --fd-file flags parse as %+v", o)
	}
}
