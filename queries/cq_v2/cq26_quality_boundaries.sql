select 'research_tier' boundary_dimension,research_tier boundary_value,count(*) assertion_count,
       sum(source_member_count) source_member_count
from research_assertions group by research_tier
union all
select 'time_role',time_role,count(*),sum(source_member_count)
from research_assertions group by time_role
union all
select 'space_role',space_role,count(*),sum(source_member_count)
from research_assertions group by space_role
union all
select 'risk_tier',risk_tier,count(*),sum(source_member_count)
from research_assertions group by risk_tier
order by boundary_dimension,boundary_value;
