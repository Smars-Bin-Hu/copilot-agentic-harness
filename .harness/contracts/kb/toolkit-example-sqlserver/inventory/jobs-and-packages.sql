-- The SQL Agent jobs and the SSIS packages deployed on one production instance, as ids of the map. Read only.
-- Save the result together with objects.sql, one id per line. Names only.
SELECT 'job:' + j.name AS id FROM msdb.dbo.sysjobs AS j WHERE j.enabled = 1
UNION ALL
SELECT 'package:' + p.name + '/' + REPLACE(k.name, '.dtsx', '')  -- the map names a package <project>/<package>
FROM SSISDB.catalog.packages AS k JOIN SSISDB.catalog.projects AS p ON p.project_id = k.project_id
ORDER BY id;
