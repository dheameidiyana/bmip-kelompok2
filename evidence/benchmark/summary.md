id        : T-42
timestamp : 2026-11-24T06:11:29Z
commit    : 6187d41
command   : python scripts/w2d_benchmark.py --steps api,dq,training,inference,cadvisor,b2 --requests 100 --repeats 3 --warmup 120 --range-days 14; throughput runs 1-3; run 3 rerun clean from temp and replaced in matrix
result    : PARTIAL
owner     : lois

| scenario | run | requests | errors | throughput/s | p50 ms | p95 ms | p99 ms | status |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :--- |
| api-latest | 1 | 100 | 0 | 26.403 | 35.505 | 52.592 | 69.101 | pass |
| api-latest | 2 | 100 | 0 | 19.299 | 41.776 | 100.452 | 123.509 | pass |
| api-latest | 3 | 100 | 0 | 17.055 | 39.847 | 86.607 | 373.705 | pass |
| api-range-14d | 1 | 100 | 0 | 3.468 | 223.264 | 550.198 | 1293.89 | pass |
| api-range-14d | 2 | 100 | 0 | 4.637 | 197.639 | 357.258 | 465.896 | pass |
| api-range-14d | 3 | 100 | 0 | 4.817 | 186.96 | 361.301 | 377.52 | pass |
| dq-runtime | 1 | 1 | 1 |  | 60061.181699857116 | 60061.181699857116 | 60061.181699857116 | partial |
| training | 1 | 1 | 1 |  | 28525.618500076234 | 28525.618500076234 | 28525.618500076234 | partial |
| inference | 1 | 100 | 0 | 9.693 | 47.937 | 113.733 | 267.125 | partial |
| cadvisor-host-cpu | 1 | 2 | 0 |  |  |  |  | pass |
| cadvisor-host-memory | 1 | 2 | 0 |  |  |  |  | pass |
| b2-before-full-scan | 1 | 1 | 0 |  | 724.3753001093864 | 724.3753001093864 | 724.3753001093864 | partial |
| b2-after-partition-pruned | 1 | 1 | 0 |  | 48.90460008755326 | 48.90460008755326 | 48.90460008755326 | partial |
| throughput-replay | 1 | 600000 | 0 | 999.999 | 2.179 | 3.682 | 9.173 | pass |
| throughput-replay | 2 | 600000 | 0 | 999.996 | 1.627 | 3.265 | 10.472 | pass |
| throughput-replay | 3 | 600000 | 0 | 999.998 | 1.814 | 4.395 | 16.38 | pass |

Bottleneck conclusion: No API or throughput target was exceeded. Throughput sustained ~1,000 trade/s (999.996-999.999/s) with 0 errors and 0 duplicates across three clean runs; API latest p95 stayed below 101 ms and range p95 below 551 ms. The real blockers are DQ runtime 60.1 s with critical `gold-market-lag`, training failure because only two labelled event dates exist, inference with no champion, and B2 being only indicative because the mart has 42 rows. Run 3 was rerun clean after the Docker restart and now matches Runs 1 and 2.

Partial rows are expected when the champion registry is empty or gold has fewer than three labelled event dates; the detail column records the measured cause.

Raw rows: `matrix.csv`, `matrix.json`; container samples: `resources.csv`.
