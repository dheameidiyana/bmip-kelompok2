# Evidence Index

Setiap klaim pada demo harus punya file bukti di direktori ini.

## Format nama file

```text
evidence/<area>/<ID>_<YYYYMMDDTHHMM>_<git-sha-pendek>.<ext>
```

Contoh: `evidence/tests/T04_20261113T1800_a1b2c3d.txt`

## Header wajib untuk file teks

```text
id        : T-04
timestamp : 2026-11-13T18:00:00Z
commit    : a1b2c3d
command   : make test
result    : PASS
owner     : dhea
```

## Environment

Isi saat evidence freeze:

- Commit SHA: `a08b0fb` (commit CP1)
- Profil compose: `dev` (`deploy/compose.base.yml` + `deploy/compose.dev.yml`)
- OS / Docker / Compose: Windows 11 Home 10.0.26200 / Docker 29.7.2 / Compose 5.5.0
- Python: 3.11.9
- Tanggal: 2026-11-11

## Indeks

| ID | Area | File | Status | Catatan |
| --- | --- | --- | --- | --- |
| CP1 | deploy | `deploy/health_20261111T0353_a08b0fb.md` | PASS | 6 service hijau, bucket + namespace + ops tables |
| CP1 | deploy | `deploy/compose-config_20261111T0353_a08b0fb.yml` | PASS | `docker compose config --no-interpolate` profil dev |
| T-01 | tests | - | pending | Tahap 2 |
| T-02 | tests | - | pending | Tahap 2 |
| T-26 | batch | - | pending | Tahap 3 |
