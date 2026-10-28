#!/usr/bin/env bash
# Read media metadata locally. Source must be mounted read-only by the caller.
set -euo pipefail
umask 077

media_root="${1:-/media}"
output_root="${2:-/output}"
probe_binary="${FFPROBE_BIN:-ffprobe}"

if [[ "$media_root" == / || ! -d "$media_root" ]]; then
  printf 'ERROR: select an existing Hacks-only directory, not /.\n' >&2
  exit 2
fi
if ! command -v "$probe_binary" >/dev/null 2>&1; then
  printf 'ERROR: ffprobe is not available in this environment.\n' >&2
  exit 2
fi
if [[ ! -d "$output_root" || ! -w "$output_root" ]]; then
  printf 'ERROR: output directory must exist and be writable.\n' >&2
  exit 2
fi

run_dir=$(mktemp -d "${output_root%/}/hacks-metadata-$(date -u +%Y%m%dT%H%M%SZ)-XXXXXX")
mkdir "$run_dir/probes"
"$probe_binary" -version > "$run_dir/ffprobe-version.txt"
# NUL-delimited paths keep spaces, Chinese characters, and newlines intact.
find "$media_root" -type f \( \
  -iname '*.mkv' -o -iname '*.mp4' -o -iname '*.m4v' -o \
  -iname '*.mov' -o -iname '*.avi' -o -iname '*.ts' -o \
  -iname '*.m2ts' -o -iname '*.webm' \) -print0 > "$run_dir/files.nul"

total=0
failed=0
while IFS= read -r -d '' media_file; do
  total=$((total + 1))
  printf -v number '%04d' "$total"
  printf 'Reading item %s\n' "$number"
  if "$probe_binary" -v error -protocol_whitelist file \
    -show_format -show_streams -show_chapters -of json -i "$media_file" \
    > "$run_dir/probes/$number.json.tmp" 2> "$run_dir/probes/$number.stderr.txt"; then
    mv "$run_dir/probes/$number.json.tmp" "$run_dir/probes/$number.json"
    printf 'ok\n' > "$run_dir/probes/$number.status.txt"
  else
    failed=$((failed + 1))
    mv "$run_dir/probes/$number.json.tmp" "$run_dir/probes/$number.failed-output.txt"
    printf 'failed\n' > "$run_dir/probes/$number.status.txt"
    printf 'Failed item %s; see its stderr.\n' "$number" >&2
  fi
done < "$run_dir/files.nul"

printf 'files=%s\nfailed=%s\n' "$total" "$failed" > "$run_dir/summary.txt"
printf 'Result directory: %s\nFiles: %s; failures: %s\n' "$run_dir" "$total" "$failed"
if (( total == 0 )); then
  printf 'ERROR: no video files found; check the mounted directory.\n' >&2
  exit 3
fi
if (( failed > 0 )); then
  exit 1
fi
