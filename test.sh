#!/usr/bin/env bash
# Compile and run the Swift characterization tests (excludes the @main app).
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$DIR/build"
for f in "$DIR"/app/*.swift; do
  n=$(wc -l < "$f")
  case "$(basename "$f")" in Localization.swift) max=1200;; *) max=600;; esac
  if [ "$n" -gt "$max" ]; then echo "$f is $n lines (max $max)"; exit 1; fi
done
SOURCES=()
for f in "$DIR"/app/*.swift; do
  [[ "$(basename "$f")" == AppEntry.swift ]] && continue
  SOURCES+=("$f")
done
swiftc -parse-as-library -framework Cocoa -framework SwiftUI \
  "${SOURCES[@]}" "$DIR"/app/Tests/*.swift -o "$DIR/build/swift-tests"
exec "$DIR/build/swift-tests"
