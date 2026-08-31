# How many rip shards the library drive can actually take

`gcrip dump --shard i/n` is meant to be run n-up on one `--out`.  Wave 2 ran ten of them.

**Ten is far too many.**  Stopping one of the last two shards made the other go from **720 to
16,560 files an hour - a 23x speed-up** on the same disc, with the same code and nothing else
changed.  The library drive is a spinning disk; ten readers seeking across it spend their time
waiting on the head, not working.

## The measurement that misled

`\PhysicalDisk(0 d:)\% Idle Time` and `Current Disk Queue Length`, sampled while the shards
happened to be in a CPU-bound phase, read **0.8% busy with a queue of 0.50** - which looks like
enormous headroom, and was used to argue for going to sixteen shards.

A rip alternates between long stretches of plugin work and heavy reads, so a single snapshot of
disk business tells you only which phase you caught.  **Measure throughput instead**: the
`plugin N/M` counter in `_logs/wave*_shard*.log` over a couple of minutes cannot be faked by a
lucky sample.

## What this cost

NBA Live 06 was written off as unfinishable at "50 files an hour, 1,100 hours remaining".  That
rate was contention, not the disc.  It was stopped on that basis - the right call for other
reasons, since it is genuinely the largest disc in the set at 63,302 plugin-format files, but
the number quoted for it was wrong.
