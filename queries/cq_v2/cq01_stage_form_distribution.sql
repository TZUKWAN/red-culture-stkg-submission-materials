select h.stage_order,m.stage_code,h.stage_label_zh,m.culture_form_code,f.label_zh culture_form_label_zh,
       m.observation_tier,sum(m.state_count) state_count,sum(m.entity_count) entity_count,
       sum(m.event_count) event_count,sum(m.supporting_fact_count) supporting_fact_count
from research_stage_region_culture_metrics m
join research_historical_stages h using(stage_code)
join research_culture_forms f using(culture_form_code)
group by h.stage_order,m.stage_code,h.stage_label_zh,m.culture_form_code,f.label_zh,m.observation_tier
order by h.stage_order,m.culture_form_code,m.observation_tier;
