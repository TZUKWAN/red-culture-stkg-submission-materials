select t.transition_id,t.transition_type,f.culture_subject_name from_subject,f.stage_label_zh from_stage,
       f.province_name from_province,x.culture_subject_name to_subject,x.stage_label_zh to_stage,
       x.province_name to_province,t.supporting_fact_count,t.confidence,t.review_status
from research_evolution_transitions t
join research_culture_states f on f.state_id=t.from_state_id
join research_culture_states x on x.state_id=t.to_state_id
order by t.transition_type,from_subject,to_subject;
