select r.counterpart_id organization_id,r.counterpart_name organization_name,
       r.counterpart_type organization_type,r.event_id,c.event_name,r.role_code,
       c.stage_code,c.province_name,c.observation_tier,r.fact_id
from research_event_roles r join research_event_spatiotemporal_cells c using(event_id)
where r.counterpart_type in ('Organization','Institution','SocialGroup')
order by r.counterpart_name,c.stage_order,c.province_name,c.event_name,r.fact_id;
