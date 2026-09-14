package main

import (
	"fmt"
	"os"
)

// Usage: credlint [-C module-dir] [patterns...]  (default ./...)
// Exit:  0 = no findings; 1 = findings, one per line; 2 = could not run.
func main() {
	dir := "."
	args := os.Args[1:]
	if len(args) >= 2 && args[0] == "-C" {
		dir, args = args[1], args[2:]
	}
	if len(args) == 0 {
		args = []string{"./..."}
	}
	_, pkgs, err := ListPackages(dir, args...)
	if err != nil {
		fmt.Fprintln(os.Stderr, "credlint:", err) // credential-logging: ok - the checker's own diagnostics: go list output and type errors
		os.Exit(2)
	}
	checker := NewChecker()
	for _, p := range pkgs {
		if err := checker.CheckPackage(p); err != nil {
			fmt.Fprintf(os.Stderr, "credlint: %s: %v\n", p.ImportPath, err) // credential-logging: ok - a type-check error naming source positions
			os.Exit(2)
		}
	}
	for _, f := range checker.Findings {
		fmt.Println(f)
	}
	if len(checker.Findings) > 0 {
		fmt.Fprintf(os.Stderr, "credlint: %d unredacted error argument(s); see relay/internal/credlint/check.go for the rule\n", len(checker.Findings))
		os.Exit(1)
	}
	fmt.Printf("credlint: %d package(s) clean\n", len(pkgs))
}
