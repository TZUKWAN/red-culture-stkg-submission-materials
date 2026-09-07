select h.stage_order,m.stage_code,r.province_name,m.culture_form_code,m.observation_tier,
       m.state_count,m.entity_count,m.event_count
from research_stage_region_culture_metrics m
join research_historical_stages h using(stage_code)
join research_study_regions r using(region_id)
order by h.stage_order,r.province_order,m.culture_form_code,m.observation_tier;
