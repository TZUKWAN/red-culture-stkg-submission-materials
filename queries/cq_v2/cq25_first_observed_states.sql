select f.culture_subject_id,s.culture_subject_name,f.culture_form_code,f.stage_order,
       s.stage_label_zh,s.province_name,s.observation_tier,f.observation_status,s.supporting_fact_count
from research_first_observed_states f join research_culture_states s using(state_id)
order by f.stage_order,s.culture_subject_name,f.culture_form_code,s.province_name;
