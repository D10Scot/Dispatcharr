package telemetry

import (
	"go/ast"
	"go/parser"
	"go/token"
	"io/fs"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"testing"
)

// censusLevels maps a logging method name to the index of its message
// argument: the key/value pairs follow it. With has no message, so its pairs
// start at index 0 (marked -1 here).
var censusLevels = map[string]int{
	"Debug": 0, "Info": 0, "Warn": 0, "Error": 0,
	"DebugContext": 1, "InfoContext": 1, "WarnContext": 1, "ErrorContext": 1,
	"Log": 2, "LogAttrs": 2,
	"With": -1,
}

// censusAttrCtors are the slog.Attr constructors whose first argument is a key.
var censusAttrCtors = map[string]bool{
	"String": true, "Int": true, "Int64": true, "Uint64": true, "Float64": true,
	"Bool": true, "Time": true, "Duration": true, "Any": true, "Group": true,
}

// censusKey is one literal key the census found and where.
type censusKey struct {
	key string
	pos token.Position
}

// logKeyCensus walks every non-test .go file under root and returns each
// string-literal key passed to a slog level call, a With call, or a slog.Attr
// constructor. It is syntactic on purpose: a call whose message argument is a
// string literal is a logging call whatever its receiver's type, so a logger
// held in a field or passed as a parameter is counted too.
func logKeyCensus(t *testing.T, root string) []censusKey {
	t.Helper()
	var found []censusKey
	fset := token.NewFileSet()
	err := filepath.WalkDir(root, func(path string, d fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if d.IsDir() {
			if d.Name() == "testdata" {
				return filepath.SkipDir
			}
			return nil
		}
		if !strings.HasSuffix(path, ".go") || strings.HasSuffix(path, "_test.go") {
			return nil
		}
		file, err := parser.ParseFile(fset, path, nil, 0)
		if err != nil {
			return err
		}
		ast.Inspect(file, func(n ast.Node) bool {
			call, ok := n.(*ast.CallExpr)
			if !ok {
				return true
			}
			sel, ok := call.Fun.(*ast.SelectorExpr)
			if !ok {
				return true
			}
			name := sel.Sel.Name
			if pkg, ok := sel.X.(*ast.Ident); ok && pkg.Name == "slog" && censusAttrCtors[name] {
				if len(call.Args) > 0 {
					if key, ok := stringLit(call.Args[0]); ok {
						found = append(found, censusKey{key, fset.Position(call.Args[0].Pos())})
					}
				}
				return true
			}
			msg, ok := censusLevels[name]
			if !ok {
				return true
			}
			if msg >= 0 {
				if len(call.Args) <= msg {
					return true
				}
				if _, ok := stringLit(call.Args[msg]); !ok {
					if _, concat := call.Args[msg].(*ast.BinaryExpr); !concat {
						return true
					}
				}
			}
			args := call.Args[msg+1:]
			for i := 0; i < len(args); i++ {
				if key, ok := stringLit(args[i]); ok {
					found = append(found, censusKey{key, fset.Position(args[i].Pos())})
					i++ // skip the value
					continue
				}
				if inner, ok := args[i].(*ast.CallExpr); ok {
					if s, ok := inner.Fun.(*ast.SelectorExpr); ok {
						if pkg, ok := s.X.(*ast.Ident); ok && pkg.Name == "slog" && censusAttrCtors[s.Sel.Name] {
							continue // an Attr; its key is counted on its own
						}
					}
				}
				i++ // a non-literal key: skip its value
			}
			return true
		})
		return nil
	})
	if err != nil {
		t.Fatalf("census walk: %v", err)
	}
	return found
}

func stringLit(e ast.Expr) (string, bool) {
	lit, ok := e.(*ast.BasicLit)
	if !ok || lit.Kind != token.STRING {
		return "", false
	}
	s, err := strconv.Unquote(lit.Value)
	return s, err == nil
}

// TestEveryLiteralLogKeyIsClassified is D9's census: every literal slog key
// the relay's non-test code writes has a rule in DefaultRules, `drop`
// included. A key without one would be dropped by SafeHandler anyway; the
// census makes that a decision someone wrote down rather than a field that
// silently never appears.
func TestEveryLiteralLogKeyIsClassified(t *testing.T) {
	found := logKeyCensus(t, "..")
	if len(found) < 50 {
		t.Fatalf("the census found %d literal keys; the walk is not reaching the module", len(found))
	}
	var missing []string
	for _, k := range found {
		if _, ok := DefaultRules.Keys[k.key]; !ok {
			missing = append(missing, k.pos.String()+": "+strconv.Quote(k.key))
		}
	}
	sort.Strings(missing)
	if len(missing) > 0 {
		t.Fatalf("literal slog keys with no rule in telemetry.DefaultRules (classify each in logkeys.go):\n%s",
			strings.Join(missing, "\n"))
	}
}

// TestCensusSeesEachCallShape keeps the census honest: each shape it claims
// to read is read, so a parse change cannot make the test above pass by
// finding nothing.
func TestCensusSeesEachCallShape(t *testing.T) {
	dir := t.TempDir()
	src := `package p

import (
	"context"
	"log/slog"
)

func f(l *slog.Logger, ctx context.Context) {
	slog.Info("m", "k_info", 1)
	l.WarnContext(ctx, "m", "k_ctx", 1)
	l.Log(ctx, slog.LevelInfo, "m", "k_log", 1)
	l.With("k_with", 1).Info("m" + "x", slog.String("k_attr", "v"), "k_after_attr", 2)
	var x struct{ Info func(int, string, int) }
	x.Info(1, "not_a_key", 2)
}
`
	if err := os.WriteFile(filepath.Join(dir, "p.go"), []byte(src), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, "p_test.go"), []byte("package p\nimport \"log/slog\"\nfunc g() { slog.Info(\"m\", \"k_test\", 1) }\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	var got []string
	for _, k := range logKeyCensus(t, dir) {
		got = append(got, k.key)
	}
	sort.Strings(got)
	want := []string{"k_after_attr", "k_attr", "k_ctx", "k_info", "k_log", "k_with"}
	if strings.Join(got, ",") != strings.Join(want, ",") {
		t.Fatalf("census keys = %v, want %v", got, want)
	}
}
