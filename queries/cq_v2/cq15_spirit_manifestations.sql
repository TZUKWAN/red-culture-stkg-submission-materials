select case when a.subject_type='Spirit' then a.subject_id else a.object_id end spirit_id,
       case when a.subject_type='Spirit' then a.subject_name else a.object_name end spirit_name,
       case when a.subject_type='Spirit' then a.object_id else a.subject_id end target_id,
       case when a.subject_type='Spirit' then a.object_name else a.subject_name end target_name,
       case when a.subject_type='Spirit' then a.object_type else a.subject_type end target_type,
       a.predicate,a.research_tier,a.fact_id
from research_assertions a
where (a.subject_type='Spirit' or a.object_type='Spirit') and a.research_tier<>'unresolved'
order by spirit_name,target_type,target_name,a.fact_id;
