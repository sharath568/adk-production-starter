---
tenant: default
title: Database Backups and Restore
---
# Backups

## Schedule

Full backups of the orders database run every night at 02:00 UTC. Incremental backups run every 15 minutes. Backups are kept for 35 days in the `larkspur-db-backups` bucket, which has object versioning and a 30-day retention lock.

## Restore

To restore to a point in time, open a change ticket first, then run `dbctl restore --target orders-restore --time "<UTC timestamp>"`. A restore of the full orders database takes about 40 minutes. Always restore into a new instance named `orders-restore` and validate row counts before switching traffic.

## Restore validation

Compare row counts for the `orders`, `payments` and `shipments` tables between the restored instance and the last known-good report. A difference larger than 0.1 percent means the restore point is wrong.
