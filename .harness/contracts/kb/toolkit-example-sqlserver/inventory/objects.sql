-- The objects of one production database, as ids of the map (`sp:Db.dbo.name`). Read only.
-- A person runs it on each production database and saves the result, one id per line, for `harness kb gaps --inventory`.
-- It returns names only: no rows, no code, no settings.
SELECT CASE o.type WHEN 'P' THEN 'sp' WHEN 'V' THEN 'view' WHEN 'U' THEN 'table' WHEN 'TR' THEN 'trigger' ELSE 'fn' END
       + ':' + DB_NAME() + '.' + SCHEMA_NAME(o.schema_id) + '.' + o.name AS id
FROM sys.objects AS o
WHERE o.type IN ('P', 'V', 'U', 'TR', 'FN', 'IF', 'TF') AND o.is_ms_shipped = 0
ORDER BY id;
