select r.counterpart_id person_id,r.counterpart_name person_name,r.event_id,c.event_name,r.role_code,
       c.stage_code,c.stage_label_zh,c.province_name,c.observation_tier,r.fact_id
from research_event_roles r join research_event_spatiotemporal_cells c using(event_id)
where r.counterpart_type='Person'
order by r.counterpart_name,c.stage_order,c.province_name,c.event_name,r.fact_id;
