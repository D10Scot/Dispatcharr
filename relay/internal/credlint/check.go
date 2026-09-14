// Package credlint is the Go side of scripts/check_credential_logging.py: a
// type-aware check that no error can reach a log line or an error message
// unredacted.
//
// THE RULE. In every non-test Go file of the module, every argument of type
// error handed to a formatting or logging call -- fmt.Errorf and its Sprint
// family, package log's Print family, and log/slog's level methods, on the
// package and on a *slog.Logger -- must be a direct call to redact.Error, or
// the call must carry a `credential-logging: ok - <reason>` comment on one
// of its own lines or the line above it. A bare reason-less marker clears
// nothing, for the reason the Python check gives: an exemption nobody has
// to justify is not reviewable.
//
// WHY THE ERROR TYPE IS THE HOOK. A provider URL reaches a Go log through
// exactly one door in this module: an error that carries it. net/http wraps
// every client failure in a *url.Error whose Error() prints the whole URL,
// and a %w or a slog "error" key hands that string to the log. 2c-2's review
// found the leak at the one *url.Error site the human guard missed; a check
// that is blind to the variable's NAME and keyed on its TYPE cannot miss
// the next one. Strings are not checked: a string argument to a log call is
// either a literal or a value the author chose to log, and the Python check
// has the same limit (it matches variable names, not values). What a string
// CAN carry -- an ffmpeg stderr line echoing the URL -- is redacted by
// redact.Line at the one site such lines are logged, and the test whose
// secret has exactly one source (channel.TestAProviderURLInStderrNeverReaches
// TheLog) is the guard for that door.
//
// KNOWN GAPS, stated as the Python check states its three. A composite
// literal that stores an error in a field (control.Unavailable{Err: err})
// is not a call and is not checked; the type's Error() method is, so the
// leak surfaces there, one hop later, which is where 2c-4 found and fixed
// one. errors.Join and a custom Error() that formats a field with %v are
// checked only if they go through the listed functions. And an error
// stringified by hand (err.Error() passed as a string) is invisible, by the
// string rule above.
//
// TYPE-CHECKED WITH THE STANDARD LIBRARY ONLY: go/parser, go/types and the
// gc export-data importer, which on this toolchain resolves standard
// packages in about a hundred milliseconds. Module-local packages are
// checked from source in dependency order (go list -deps), so
// github.com/.../relay/redact resolves to the real package and the
// allowlist below is a full name, not a guess.
package main

import (
	"bytes"
	"context"
	"fmt"
	"go/ast"
	"go/importer"
	"go/parser"
	"go/token"
	"go/types"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strings"
)

// Marker is the exemption comment, modelled on `# credential-logging: ignore
// - <reason>` on the Python side and `# zizmor: ignore[...]` before it.
const Marker = "credential-logging: ok"

// Redactors are the functions an error may pass through on its way to a
// log or a message. One entry; a second implementation would be a second
// thing to remember.
var Redactors = map[string]bool{
	"github.com/D10Scot/Dispatcharr/relay/redact.Error": true,
}

// Sinks are the functions whose error-typed arguments are checked, by
// go/types full name. Methods are spelled the way types.Func.FullName
// spells them.
var Sinks = map[string]bool{
	"fmt.Errorf": true, "fmt.Sprintf": true, "fmt.Sprint": true, "fmt.Sprintln": true,
	"fmt.Fprintf": true, "fmt.Fprint": true, "fmt.Fprintln": true,
	"fmt.Printf": true, "fmt.Print": true, "fmt.Println": true,
	"log.Printf": true, "log.Print": true, "log.Println": true,
	"log.Fatalf": true, "log.Fatal": true, "log.Fatalln": true,
	"log.Panicf": true, "log.Panic": true, "log.Panicln": true,
	"log/slog.Error": true, "log/slog.Warn": true, "log/slog.Info": true, "log/slog.Debug": true, "log/slog.Log": true,
	"log/slog.ErrorContext": true, "log/slog.WarnContext": true, "log/slog.InfoContext": true, "log/slog.DebugContext": true,
	"log/slog.Any":             true,
	"(*log/slog.Logger).Error": true, "(*log/slog.Logger).Warn": true, "(*log/slog.Logger).Info": true,
	"(*log/slog.Logger).Debug": true, "(*log/slog.Logger).Log": true, "(*log/slog.Logger).With": true,
	"(*log/slog.Logger).ErrorContext": true, "(*log/slog.Logger).WarnContext": true,
	"(*log/slog.Logger).InfoContext": true, "(*log/slog.Logger).DebugContext": true,
}

// Finding is one unredacted error argument.
type Finding struct {
	Pos    token.Position
	Callee string
	Arg    int
	Reason string
}

func (f Finding) String() string {
	return fmt.Sprintf("%s: %s argument %d has type error and is not redacted: %s", f.Pos, f.Callee, f.Arg, f.Reason)
}

// Package is one module package to check: its import path, directory and
// non-test Go files, as `go list` reports them.
type Package struct {
	ImportPath string
	Dir        string
	Files      []string
}

// ListPackages runs `go list -deps` on the patterns and returns the
// module's own packages in dependency order.
func ListPackages(moduleDir string, patterns ...string) (module string, pkgs []Package, err error) {
	out, err := goList(moduleDir, "-m", "-f", "{{.Path}}")
	if err != nil {
		return "", nil, err
	}
	module = strings.TrimSpace(out)

	args := append([]string{"-deps", "-f", "{{.ImportPath}}\t{{.Dir}}\t{{join .GoFiles \",\"}}"}, patterns...)
	out, err = goList(moduleDir, args...)
	if err != nil {
		return "", nil, err
	}
	for _, line := range strings.Split(strings.TrimSpace(out), "\n") {
		parts := strings.SplitN(line, "\t", 3)
		if len(parts) != 3 || !strings.HasPrefix(parts[0], module) {
			continue
		}
		var files []string
		for _, f := range strings.Split(parts[2], ",") {
			if f != "" {
				files = append(files, filepath.Join(parts[1], f))
			}
		}
		pkgs = append(pkgs, Package{ImportPath: parts[0], Dir: parts[1], Files: files})
	}
	return module, pkgs, nil
}

func goList(dir string, args ...string) (string, error) {
	// #nosec G204,G702 -- the go tool with fixed flags and the caller's
	// package patterns; both rule ids are needed, the taint rule G702 fires
	// on the same line once G204 is silenced (the G304/G703 pairing 2c-1
	// found, on a different rule pair).
	cmd := exec.CommandContext(context.Background(), "go", append([]string{"list"}, args...)...)
	cmd.Dir = dir
	var stderr bytes.Buffer
	cmd.Stderr = &stderr
	out, err := cmd.Output()
	if err != nil {
		return "", fmt.Errorf("go list %s: %w: %s", strings.Join(args, " "), err, stderr.String()) // credential-logging: ok - the go tool's own diagnostics about package paths
	}
	return string(out), nil
}

// Checker type-checks packages in order and collects findings.
type Checker struct {
	fset     *token.FileSet
	std      types.Importer
	checked  map[string]*types.Package
	Findings []Finding
}

// NewChecker builds a checker whose standard-library imports come from the
// gc importer.
func NewChecker() *Checker {
	fset := token.NewFileSet()
	return &Checker{fset: fset, std: importer.ForCompiler(fset, "gc", nil), checked: map[string]*types.Package{}}
}

// Import satisfies types.Importer: a module package already checked is
// returned from the cache, everything else goes to the gc importer.
func (c *Checker) Import(path string) (*types.Package, error) {
	if pkg, ok := c.checked[path]; ok {
		return pkg, nil
	}
	return c.std.Import(path)
}

// CheckSources type-checks one package given as file name to source, for
// tests and for CheckPackage.
func (c *Checker) CheckSources(importPath string, sources map[string]string) error {
	var files []*ast.File
	names := make([]string, 0, len(sources))
	for name := range sources {
		names = append(names, name)
	}
	sort.Strings(names)
	for _, name := range names {
		f, err := parser.ParseFile(c.fset, name, sources[name], parser.ParseComments)
		if err != nil {
			return err
		}
		files = append(files, f)
	}
	info := &types.Info{Types: map[ast.Expr]types.TypeAndValue{}, Uses: map[*ast.Ident]types.Object{}, Selections: map[*ast.SelectorExpr]*types.Selection{}}
	conf := types.Config{Importer: c}
	pkg, err := conf.Check(importPath, c.fset, files, info)
	if err != nil {
		return err
	}
	c.checked[importPath] = pkg
	for _, f := range files {
		c.inspect(f, info)
	}
	return nil
}

// CheckPackage reads a package's files and checks them.
func (c *Checker) CheckPackage(p Package) error {
	sources := map[string]string{}
	for _, name := range p.Files {
		raw, err := os.ReadFile(name) // #nosec G304 -- a path `go list` reported for a package the caller named
		if err != nil {
			return err
		}
		sources[name] = string(raw)
	}
	return c.CheckSources(p.ImportPath, sources)
}

var errorType = types.Universe.Lookup("error").Type().Underlying().(*types.Interface)

func (c *Checker) inspect(f *ast.File, info *types.Info) {
	markers := markerLines(c.fset, f)
	ast.Inspect(f, func(n ast.Node) bool {
		call, ok := n.(*ast.CallExpr)
		if !ok {
			return true
		}
		callee := calleeName(call, info)
		if !Sinks[callee] {
			return true
		}
		for i, arg := range call.Args {
			tv, ok := info.Types[arg]
			if !ok || tv.Type == nil {
				continue
			}
			if !types.Implements(tv.Type, errorType) && !types.Implements(types.NewPointer(tv.Type), errorType) {
				continue
			}
			if isNil(tv) {
				continue
			}
			if inner, ok := arg.(*ast.CallExpr); ok && Redactors[calleeName(inner, info)] {
				continue
			}
			start := c.fset.Position(call.Pos())
			end := c.fset.Position(call.End())
			if reason, ok := markerFor(markers, start.Line, end.Line); ok {
				if reason == "" {
					c.Findings = append(c.Findings, Finding{Pos: start, Callee: callee, Arg: i,
						Reason: "the credential-logging marker has no reason; write `credential-logging: ok - <why this cannot carry a URL>`"})
				}
				continue
			}
			c.Findings = append(c.Findings, Finding{Pos: start, Callee: callee, Arg: i,
				Reason: "wrap it in redact.Error(...) or add `// credential-logging: ok - <reason>` on the call"})
		}
		return true
	})
}

func isNil(tv types.TypeAndValue) bool { return tv.IsNil() }

// calleeName resolves a call's function to go/types' full name, or "".
func calleeName(call *ast.CallExpr, info *types.Info) string {
	var id *ast.Ident
	switch fn := call.Fun.(type) {
	case *ast.Ident:
		id = fn
	case *ast.SelectorExpr:
		id = fn.Sel
	default:
		return ""
	}
	obj, ok := info.Uses[id]
	if !ok {
		return ""
	}
	fn, ok := obj.(*types.Func)
	if !ok {
		return ""
	}
	return fn.FullName()
}

// markerLines maps a line number to the marker's reason ("" when the
// marker has none) for every comment carrying it.
func markerLines(fset *token.FileSet, f *ast.File) map[int]string {
	out := map[int]string{}
	for _, group := range f.Comments {
		for _, comment := range group.List {
			text := comment.Text
			idx := strings.Index(text, Marker)
			if idx < 0 {
				continue
			}
			rest := strings.TrimSpace(text[idx+len(Marker):])
			reason := ""
			if strings.HasPrefix(rest, "-") {
				reason = strings.TrimSpace(strings.TrimPrefix(rest, "-"))
			}
			out[fset.Position(comment.Pos()).Line] = reason
		}
	}
	return out
}

// markerFor finds a marker on any line the call spans, or the line above
// its first, and reports its reason.
func markerFor(markers map[int]string, start, end int) (string, bool) {
	for line := start - 1; line <= end; line++ {
		if reason, ok := markers[line]; ok {
			return reason, true
		}
	}
	return "", false
}
