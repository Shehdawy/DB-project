-- Baseline, unfiltered business-question views. Filtered equivalents in app.py use the same population CTE.
CREATE OR REPLACE VIEW vw_bq01 AS
 SELECT b.brand_name, COUNT(*)::bigint AS perfume_count, SUM(p.rating_count)::bigint AS total_votes,
        ROUND(AVG(p.rating_value),3) AS average_rating,
        ROUND(SUM(p.rating_value*p.rating_count)/NULLIF(SUM(p.rating_count),0),3) AS weighted_rating
 FROM perfume p JOIN brand b ON p.brand_id=b.brand_id
 GROUP BY b.brand_id,b.brand_name HAVING SUM(p.rating_count)>=100
 ORDER BY average_rating DESC, total_votes DESC LIMIT 10;
CREATE OR REPLACE VIEW vw_bq02 AS
 SELECT ms.segment_name, COUNT(*)::bigint AS perfume_count,
        ROUND(AVG(p.rating_value),3) AS average_rating, SUM(p.rating_count)::bigint AS total_votes
 FROM perfume p JOIN brand b ON b.brand_id=p.brand_id JOIN market_segment ms ON ms.segment_id=b.segment_id
 GROUP BY ms.segment_id,ms.segment_name ORDER BY perfume_count DESC;
CREATE OR REPLACE VIEW vw_bq03 AS
 SELECT cg.group_name, COUNT(*)::bigint AS perfume_count,
        ROUND(100.0*COUNT(*)/NULLIF((SELECT COUNT(*) FROM perfume),0),2) AS dataset_percentage,
        ROUND(AVG(p.rating_value),3) AS average_rating
 FROM perfume p JOIN brand b ON b.brand_id=p.brand_id JOIN corporate_group cg ON cg.group_id=b.group_id
 GROUP BY cg.group_id,cg.group_name ORDER BY perfume_count DESC;
CREATE OR REPLACE VIEW vw_bq04 AS
 SELECT g.gender_name, COUNT(*)::bigint AS perfume_count,ROUND(AVG(p.rating_value),3) AS average_rating
 FROM perfume p JOIN gender g ON p.gender_id=g.gender_id GROUP BY g.gender_id,g.gender_name ORDER BY perfume_count DESC;
CREATE OR REPLACE VIEW vw_bq05 AS
 SELECT c.concentration_name,COUNT(*)::bigint AS perfume_count,ROUND(AVG(p.rating_value),3) AS average_rating
 FROM perfume p JOIN concentration c ON p.concentration_id=c.concentration_id
 GROUP BY c.concentration_id,c.concentration_name ORDER BY perfume_count DESC;
CREATE OR REPLACE VIEW vw_bq06 AS
 SELECT (p.release_year/10)*10 AS release_decade, COUNT(*)::bigint AS perfume_count,
        ROUND(AVG(p.rating_value),3) AS average_rating, SUM(p.rating_count)::bigint AS total_votes
 FROM perfume p GROUP BY (p.release_year/10)*10 ORDER BY release_decade;
CREATE OR REPLACE VIEW vw_bq07 AS
 SELECT a.accord_name,COUNT(DISTINCT pa.perfume_id)::bigint AS perfume_count
 FROM perfume_accord pa JOIN accord a USING(accord_id)
 GROUP BY a.accord_id,a.accord_name ORDER BY perfume_count DESC LIMIT 15;
CREATE OR REPLACE VIEW vw_bq08 AS
 SELECT note_layer,note_name,perfume_count FROM (
   SELECT pn.note_layer,n.note_name,COUNT(DISTINCT pn.perfume_id)::bigint AS perfume_count,
          ROW_NUMBER() OVER (PARTITION BY pn.note_layer ORDER BY COUNT(DISTINCT pn.perfume_id) DESC,n.note_name) AS rank_in_layer
   FROM perfume_note pn JOIN note n USING(note_id) GROUP BY pn.note_layer,n.note_id,n.note_name
 ) x WHERE rank_in_layer<=10;
CREATE OR REPLACE VIEW vw_bq09 AS
 SELECT f.family_name, COUNT(*)::bigint AS perfume_count, SUM(p.rating_count)::bigint AS total_votes,
        ROUND(AVG(p.rating_value),3) AS average_rating
 FROM perfume p JOIN fragrance_family f ON f.family_id=p.family_id
 GROUP BY f.family_id,f.family_name ORDER BY perfume_count DESC;
CREATE OR REPLACE VIEW vw_bq10 AS
 SELECT p.perfume_id,p.name,b.brand_name,p.rating_value,p.rating_count,p.release_year,p.url
 FROM perfume p JOIN brand b ON b.brand_id=p.brand_id ORDER BY p.rating_count DESC,p.perfume_id LIMIT 20;
