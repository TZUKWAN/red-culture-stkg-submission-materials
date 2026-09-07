select case when c.publication_eligible=1 then 'published' else 'candidate' end publication_status,
       coalesce(t.transition_id,c.candidate_id) candidate_or_transition_id,c.transition_type,
       f.culture_subject_name source_subject,f.culture_subject_type source_type,
       x.culture_subject_name target_subject,x.culture_subject_type target_type,
       x.stage_label_zh,x.province_name,c.supporting_fact_id
from research_evolution_transition_candidates c
join research_culture_states f on f.state_id=c.from_state_id
join research_culture_states x on x.state_id=c.to_state_id
left join research_evolution_transition_support ts on ts.candidate_id=c.candidate_id
left join research_evolution_transitions t on t.transition_id=ts.transition_id
where c.transition_type in ('memorialized_as','transformed_into','institutionalized_as','adapted_as','digitized_as')
order by publication_status desc,c.transition_type,source_subject,target_subject;
