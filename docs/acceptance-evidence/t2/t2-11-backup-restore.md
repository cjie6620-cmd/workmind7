# T2-11 Backup / Restore Drill

- Date: 2026-07-16 16:50:29
- Engine: PostgreSQL 16 + pgvector (compose prod)
- Dump tool: `pg_dump --clean --if-exists`
- Dump file: `pg-dump-20260716-165027.sql` (29688 bytes)
- Marker row: `t2_backup_e138dada` present in dump and re-verified after simulated loss
- `alembic upgrade head` duration: 0.87s (already at head)
- RPO target (this drill): last successful dump (file on host evidence dir)
- RTO observed: dump+verify path < 5 minutes on this dataset

Pass for quasi-prod compose volume; production-scale WAL timing still recommended later.
