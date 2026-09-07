select time_role,coalesce(time_precision,'unknown') time_precision,count(*) assertion_count,
       sum(case when normalized_time_label is not null then 1 else 0 end) normalized_time_count,
       count(distinct time_owner_id) owner_count
from research_assertions
group by time_role,coalesce(time_precision,'unknown')
order by time_role,time_precision;
