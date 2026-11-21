-- Descriptive checks: expected counts are a reference, never used to rewrite/force the data.
SELECT object_name, actual, expected, actual - expected AS difference,
       CASE WHEN actual=expected THEN 'PASS' ELSE 'REVIEW' END AS status
FROM (
 SELECT 'perfume' object_name, (SELECT COUNT(*) FROM perfume) actual, 40000::bigint expected
 UNION ALL SELECT 'brand',(SELECT COUNT(*) FROM brand),1525
 UNION ALL SELECT 'accord',(SELECT COUNT(*) FROM accord),87
 UNION ALL SELECT 'note',(SELECT COUNT(*) FROM note),1823
 UNION ALL SELECT 'perfume_accord',(SELECT COUNT(*) FROM perfume_accord),347456
 UNION ALL SELECT 'perfume_note',(SELECT COUNT(*) FROM perfume_note),388317
) checks ORDER BY object_name;

SELECT
 (SELECT COUNT(*) FROM perfume WHERE brand_id IS NULL OR gender_id IS NULL OR concentration_id IS NULL OR family_id IS NULL) AS null_perfume_fks,
 (SELECT COUNT(*) FROM brand WHERE segment_id IS NULL OR group_id IS NULL) AS null_brand_fks,
 (SELECT COUNT(*) FROM perfume p WHERE NOT EXISTS (SELECT 1 FROM perfume_accord pa WHERE pa.perfume_id=p.perfume_id)) AS perfumes_without_accord,
 (SELECT COUNT(*) FROM perfume p WHERE NOT EXISTS (SELECT 1 FROM perfume_note pn WHERE pn.perfume_id=p.perfume_id)) AS perfumes_without_note,
 (SELECT COUNT(*) FROM perfume WHERE rating_value NOT BETWEEN 1 AND 5 OR rating_count < 0 OR release_year NOT BETWEEN 1500 AND 2100) AS invalid_values,
 (SELECT COUNT(*) FROM (SELECT perfume_id, accord_id FROM perfume_accord GROUP BY 1,2 HAVING COUNT(*)>1) d) AS duplicate_accord_relations,
 (SELECT COUNT(*) FROM (SELECT perfume_id, note_id, note_layer FROM perfume_note GROUP BY 1,2,3 HAVING COUNT(*)>1) d) AS duplicate_note_relations;

SELECT p.perfume_id,p.name,b.brand_name,p.release_year,p.rating_value,p.rating_count,
       (SELECT string_agg(a.accord_name,';' ORDER BY pa.accord_rank) FROM perfume_accord pa JOIN accord a USING(accord_id) WHERE pa.perfume_id=p.perfume_id) AS main_accords,
       (SELECT string_agg(n.note_name,';' ORDER BY n.note_name) FROM perfume_note pn JOIN note n USING(note_id) WHERE pn.perfume_id=p.perfume_id AND pn.note_layer='Base') AS base_notes
FROM perfume p JOIN brand b USING(brand_id) ORDER BY p.perfume_id LIMIT 3;
