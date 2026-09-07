select c.event_id,c.event_name,c.stage_code,c.stage_label_zh,c.province_name,
       f.controlled_role_count,
       count(distinct case when r.counterpart_type='Person' then r.counterpart_id end) person_count,
       count(distinct case when r.counterpart_type in ('Organization','Institution','SocialGroup') then r.counterpart_id end) organization_count,
       count(distinct case when r.counterpart_type in ('CreativeWork','Document','Artifact','Spirit','ValueFacet') then r.counterpart_id end) culture_object_count
from research_event_spatiotemporal_cells c
join research_event_frames f using(event_id)
left join research_event_roles r using(event_id)
where c.observation_tier='trusted_event_spacetime'
group by c.cell_id,c.event_id,c.event_name,c.stage_code,c.stage_label_zh,c.province_name,f.controlled_role_count
order by culture_object_count desc,person_count desc,organization_count desc,c.event_name;
