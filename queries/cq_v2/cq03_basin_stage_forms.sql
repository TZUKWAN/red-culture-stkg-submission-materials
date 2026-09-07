select s.stage_order,s.stage_code,b.basin_section_name,s.culture_form_code,s.observation_tier,
       count(*) state_count,count(distinct s.culture_subject_id) entity_count,
       count(distinct e.event_id) event_count
from research_culture_states s
join research_basin_sections b using(basin_section_id)
join research_culture_state_events e using(state_id)
group by s.stage_order,s.stage_code,b.basin_section_name,s.culture_form_code,s.observation_tier
order by s.stage_order,b.section_order,s.culture_form_code,s.observation_tier;
