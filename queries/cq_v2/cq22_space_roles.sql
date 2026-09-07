select space_role,count(*) assertion_count,count(distinct canonical_space_anchor_id) anchor_count,
       sum(case when province is not null then 1 else 0 end) province_count,
       sum(case when city is not null then 1 else 0 end) city_count,
       sum(case when county is not null then 1 else 0 end) county_count
from research_assertions
group by space_role
order by space_role;
