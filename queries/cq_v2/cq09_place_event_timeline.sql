select r.counterpart_id place_id,r.counterpart_name place_name,r.counterpart_type place_type,
       r.event_id,c.event_name,r.role_code,c.stage_code,c.province_name,c.observation_tier,r.fact_id
from research_event_roles r join research_event_spatiotemporal_cells c using(event_id)
where r.counterpart_type in ('Place','AdministrativeRegion','CulturalSite')
order by r.counterpart_name,c.stage_order,c.event_name,r.fact_id;
