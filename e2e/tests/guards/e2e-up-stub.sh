#!/usr/bin/env bash
# A stateful stand-in for `docker` (and, with STUB_AS=curl, for `curl`), for
# e2e-up-stacks.spec.ts. It answers exactly the invocations
# scripts/e2e_up.sh makes and nothing else, so a change to the script that
# reaches for a shape this stub does not recognise fails loudly (exit 97,
# an UNHANDLED line in the log) instead of silently passing a test that
# never actually exercised the new code.
#
# State lives under $STUB_STATE as plain files, so the spec can seed it
# before a run and read it back after one:
#
#   $STUB_STATE/log                 one line per invocation: "<argv>"
#   $STUB_STATE/c/<name>/image      image id the container was created from
#   $STUB_STATE/c/<name>/running    present when running
#   $STUB_STATE/c/<name>/networks   one network per line
#   $STUB_STATE/c/<name>/env        one -e value per line (from `run`)
#   $STUB_STATE/n/<name>            a network exists
#   $STUB_STATE/v/<name>            a volume exists
#   $STUB_STATE/i/<tag>             image id for a tag
#
# Every claim this script encodes about Docker's real output (the range
# template over .NetworkSettings.Networks, a missing object's exit 1 and
# blank stdout line, a stopped container still listing its network
# attachments) is re-checked against real Docker in Task 1.4 -- a stub is
# exactly what hid #261's first bug, so a mismatch there is a bug in THIS
# script, not in the one under test.
set -u
shopt -s nullglob

STATE="${STUB_STATE:?STUB_STATE not set}"
LOG="$STATE/log"
mkdir -p "$STATE/c" "$STATE/n" "$STATE/v" "$STATE/i"

log_call() {
  printf '%s\n' "$*" >>"$LOG"
}

unhandled() {
  printf 'UNHANDLED %s\n' "$*" >>"$LOG"
  exit 97
}

container_dir() {
  printf '%s/c/%s' "$STATE" "$1"
}

# curl stand-in. e2e_up.sh only ever polls readiness with `curl -sf`, and no
# guard test needs that loop to iterate, so every call just succeeds.
if [[ "${STUB_AS:-}" == curl ]]; then
  log_call "curl $*"
  exit 0
fi

log_call "docker $*"

cmd="${1:-}"
shift || true

case "$cmd" in
  inspect)
    # `inspect -f TEMPLATE NAME`, order-agnostic (real docker accepts either
    # order too).
    fmt=""
    name=""
    while [[ $# -gt 0 ]]; do
      case "$1" in
        -f)
          fmt="$2"
          shift 2
          ;;
        *)
          name="$1"
          shift
          ;;
      esac
    done
    dir="$(container_dir "$name")"
    case "$fmt" in
      '{{range $n, $_ := .NetworkSettings.Networks}}{{println $n}}{{end}}')
        if [[ ! -d "$dir" ]]; then
          echo ""
          echo "error: no such object: $name" >&2
          exit 1
        fi
        [[ -f "$dir/networks" ]] && cat "$dir/networks"
        echo ""
        ;;
      '{{.Image}}')
        if [[ ! -d "$dir" ]] || [[ ! -f "$dir/image" ]]; then
          echo ""
          echo "error: no such object: $name" >&2
          exit 1
        fi
        cat "$dir/image"
        ;;
      '{{.State.Running}}')
        if [[ ! -d "$dir" ]]; then
          echo ""
          echo "error: no such object: $name" >&2
          exit 1
        fi
        if [[ -f "$dir/running" ]]; then echo true; else echo false; fi
        ;;
      *)
        unhandled "inspect" "-f" "$fmt" "$name"
        ;;
    esac
    ;;
  image)
    sub="${1:-}"
    shift || true
    case "$sub" in
      inspect)
        fmt=""
        tag=""
        while [[ $# -gt 0 ]]; do
          case "$1" in
            -f)
              fmt="$2"
              shift 2
              ;;
            *)
              tag="$1"
              shift
              ;;
          esac
        done
        if [[ -z "$tag" ]] || [[ ! -f "$STATE/i/$tag" ]]; then exit 1; fi
        cat "$STATE/i/$tag"
        ;;
      *)
        unhandled "image" "$sub" "$@"
        ;;
    esac
    ;;
  build)
    # We only care about -t TAG; every other flag (-f, --build-arg,
    # --provenance, the trailing context path) is accepted and ignored.
    tag=""
    prev=""
    for a in "$@"; do
      if [[ "$prev" == "-t" ]]; then tag="$a"; fi
      prev="$a"
    done
    if [[ -z "$tag" ]]; then unhandled "build" "$@"; fi
    printf '%s\n' "${STUB_NEXT_IMAGE_ID:-sha256:new}" >"$STATE/i/$tag"
    ;;
  network)
    sub="${1:-}"
    shift || true
    case "$sub" in
      inspect)
        # `network inspect N` (existence only) or, with -f, B-7's gateway
        # template -- answered unconditionally, per the overlap note: an
        # extra recognised shape harms nothing and the UNHANDLED catch-all
        # still guards every other one.
        fmt=""
        name=""
        while [[ $# -gt 0 ]]; do
          case "$1" in
            -f)
              fmt="$2"
              shift 2
              ;;
            *)
              name="$1"
              shift
              ;;
          esac
        done
        if [[ -n "$fmt" ]]; then
          case "$fmt" in
            '{{(index .IPAM.Config 0).Gateway}}')
              [[ -f "$STATE/n/$name" ]] && echo "172.30.0.1" || exit 1
              ;;
            *)
              unhandled "network" "inspect" "-f" "$fmt" "$name"
              ;;
          esac
        else
          [[ -f "$STATE/n/$name" ]] && exit 0 || exit 1
        fi
        ;;
      create)
        : >"$STATE/n/$1"
        ;;
      rm)
        rm -f "$STATE/n/$1"
        ;;
      connect)
        net="$1"
        c="$2"
        dir="$(container_dir "$c")"
        mkdir -p "$dir"
        if ! { [[ -f "$dir/networks" ]] && grep -qxF "$net" "$dir/networks"; }; then
          printf '%s\n' "$net" >>"$dir/networks"
        fi
        ;;
      disconnect)
        net="$1"
        c="$2"
        dir="$(container_dir "$c")"
        if [[ -f "$dir/networks" ]]; then
          grep -vxF "$net" "$dir/networks" >"$dir/networks.tmp" || true
          mv "$dir/networks.tmp" "$dir/networks"
        fi
        ;;
      *)
        unhandled "network" "$sub" "$@"
        ;;
    esac
    ;;
  rm)
    name=""
    for a in "$@"; do
      [[ "$a" == -* ]] || name="$a"
    done
    if [[ -z "$name" ]]; then unhandled "rm" "$@"; fi
    dir="$(container_dir "$name")"
    if [[ ! -d "$dir" ]]; then exit 1; fi
    rm -rf "$dir"
    ;;
  stop)
    name="${1:-}"
    dir="$(container_dir "$name")"
    if [[ ! -d "$dir" ]]; then exit 1; fi
    rm -f "$dir/running"
    ;;
  start)
    name="${1:-}"
    dir="$(container_dir "$name")"
    if [[ ! -d "$dir" ]]; then exit 1; fi
    : >"$dir/running"
    ;;
  run)
    # `run -d --name C --network N -p ... [-e K=V]... [-v ...] IMAGE`
    name=""
    network=""
    image=""
    envs=""
    while [[ $# -gt 0 ]]; do
      case "$1" in
        -d)
          shift
          ;;
        --name)
          name="$2"
          shift 2
          ;;
        --network)
          network="$2"
          shift 2
          ;;
        -p)
          shift 2
          ;;
        -e)
          envs="${envs}${2}"$'\n'
          shift 2
          ;;
        -v)
          shift 2
          ;;
        *)
          image="$1"
          shift
          ;;
      esac
    done
    if [[ -z "$name" ]]; then unhandled "run(no --name)" ; fi
    dir="$(container_dir "$name")"
    mkdir -p "$dir"
    : >"$dir/running"
    [[ -n "$network" ]] && printf '%s\n' "$network" >"$dir/networks"
    printf '%s' "$envs" >"$dir/env"
    if [[ -n "$image" ]] && [[ -f "$STATE/i/$image" ]]; then
      cp "$STATE/i/$image" "$dir/image"
    else
      printf '%s\n' "${STUB_NEXT_IMAGE_ID:-sha256:new}" >"$dir/image"
    fi
    ;;
  ps)
    all=0
    for a in "$@"; do
      [[ "$a" == "-a" ]] && all=1
    done
    for d in "$STATE"/c/*/; do
      n="$(basename "$d")"
      if [[ $all -eq 1 ]] || [[ -f "$d/running" ]]; then
        echo "$n"
      fi
    done
    ;;
  volume)
    sub="${1:-}"
    shift || true
    case "$sub" in
      rm)
        rm -f "$STATE/v/$1"
        ;;
      *)
        unhandled "volume" "$sub" "$@"
        ;;
    esac
    ;;
  logs)
    exit 0
    ;;
  *)
    unhandled "$cmd" "$@"
    ;;
esac
