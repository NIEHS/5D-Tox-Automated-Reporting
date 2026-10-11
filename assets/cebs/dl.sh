#!/bin/bash
cd /workspace/rlm-bmdx/assets/cebs
while IFS=$'\t' read -r id name url; do
  out="$id/$name"
  [ -s "$out" ] && continue
  printf '%s\t%s\t%s\n' "$id" "$name" "$url"
done < jobs.tsv | xargs -P 3 -d '\n' -I{} bash -c 'IFS=$'"'"'\t'"'"' read -r id name url <<< "{}"; code=$(curl -sS -L --connect-timeout 30 --speed-time 120 --speed-limit 1024 --retry 3 --retry-delay 10 --retry-all-errors -o "$id/$name.part" -w "%{http_code}" "$url") && [ "$code" = 200 ] && mv "$id/$name.part" "$id/$name" && echo "OK $id $name" || echo "FAIL $code $id $name"' > dl.log 2>&1
echo DONE >> dl.log
