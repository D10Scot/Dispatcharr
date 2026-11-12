package telemetry

import (
	"io"
	"log"
	"log/slog"
	"os"
)

// InstallEarlyLogger is the first thing relay/main.go does (D8): with
// MINO_LOG_FORMAT=json it makes slog.Default a SafeHandler over the JSON
// handler on w, so config.Load's failure line and every line before Init is
// already JSON and already cleaned. With any other value it changes nothing:
// the text format stays byte-identical to today. getenv is os.Getenv when nil.
//
// It reads the variable itself rather than calling LoadConfig, whose warnings
// would be written before the handler they belong in exists; LoadConfig, run
// after it, writes them through this handler instead.
func InstallEarlyLogger(getenv func(string) string, w io.Writer) {
	if getenv == nil {
		getenv = os.Getenv
	}
	if getenv(envLogFormat) != LogFormatJSON {
		return
	}
	installJSON(NewSafeHandler(NewJSONHandler(w, slog.LevelInfo), DefaultRules, &ChannelIDs{}))
}

// InstallLogger installs t's log handler as slog.Default once Init has built
// it, replacing the early one (D8):
//
//   - JSON: SafeHandler over the JSON handler on w and, when the OTLP log
//     signal is on, the otelslog bridge, with the channel id map Init filled.
//   - text with no OTLP logs: nothing changes, byte-identical to today.
//   - text with OTLP logs: the existing text handler and the bridge, fanned
//     out. Package log's output is then put back on w with its flags and
//     prefix, so a log.Printf line keeps today's text and bypasses the bridge:
//     slog's own default handler writes through package log, and leaving
//     package log pointed at the new default would make that handler call
//     itself and deadlock.
func (t *Telemetry) InstallLogger(w io.Writer) {
	if t.cfg.LogFormat == LogFormatJSON {
		installJSON(t.LogHandler(w, nil))
		return
	}
	text := slog.Default().Handler()
	h := t.LogHandler(w, text)
	if h == text {
		return
	}
	flags, prefix := log.Flags(), log.Prefix()
	slog.SetDefault(slog.New(h))
	log.SetOutput(w)
	log.SetFlags(flags)
	log.SetPrefix(prefix)
}

// installJSON makes h the default for slog and, through slog.SetDefault's
// bridge, for package log. The prefix is dropped: a JSON record's msg is the
// message alone, and the program is named by mino.program.
func installJSON(h slog.Handler) {
	slog.SetDefault(slog.New(h))
	log.SetPrefix("")
}
