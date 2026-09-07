select s.culture_subject_id,s.culture_subject_name,s.culture_subject_type,s.culture_form_code,
       s.stage_order,s.stage_label_zh,s.province_name,b.basin_section_name,s.observation_tier,
       s.supporting_fact_count,s.supporting_event_count
from research_culture_states s join research_basin_sections b using(basin_section_id)
order by s.culture_subject_name,s.culture_form_code,s.stage_order,s.province_name,s.observation_tier;
