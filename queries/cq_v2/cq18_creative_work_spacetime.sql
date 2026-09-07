select s.culture_subject_id work_id,s.culture_subject_name work_name,m.media_type,s.stage_order,
       s.stage_label_zh,s.province_name,b.basin_section_name,s.observation_tier,s.supporting_fact_count
from research_culture_states s
join research_creative_work_media m on m.entity_id=s.culture_subject_id
join research_basin_sections b using(basin_section_id)
order by s.stage_order,s.province_name,m.media_type,s.culture_subject_name;
