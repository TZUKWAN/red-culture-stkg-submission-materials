select m.value_facet_id,m.value_facet_name,
       count(distinct s.stage_code) stage_count,count(distinct s.region_id) region_count,
       min(s.stage_order) first_observed_stage_order,max(s.stage_order) last_observed_stage_order,
       count(distinct s.state_id) state_count,count(distinct m.spirit_value_fact_id) supporting_fact_count
from research_culture_state_value_facets m join research_culture_states s using(state_id)
group by m.value_facet_id,m.value_facet_name
order by stage_count desc,region_count desc,value_facet_name;
