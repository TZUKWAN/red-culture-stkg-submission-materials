select entity_type,type_validation_status,count(*) entity_count,
       sum(integrated_member_count) integrated_member_count,
       sum(case when aliases_json<>'[]' then 1 else 0 end) alias_entity_count
from research_entities
group by entity_type,type_validation_status
order by entity_type,type_validation_status;
