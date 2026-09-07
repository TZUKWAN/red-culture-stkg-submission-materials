select entity_id,canonical_name,entity_type,integrated_member_count,source_entity_count,
       aliases_json,type_validation_status
from research_entities
where integrated_member_count>1 or aliases_json<>'[]'
order by integrated_member_count desc,canonical_name,entity_id;
