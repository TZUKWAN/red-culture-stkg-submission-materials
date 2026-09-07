with total as (select count(*) n from research_creative_work_media)
select m.media_type,count(*) work_count,round(1.0*count(*)/total.n,6) share,
       count(distinct m.classification_method) classification_method_count,
       sum(case when m.media_type='未知' then 1 else 0 end) unknown_count
from research_creative_work_media m cross join total
group by m.media_type,total.n
order by work_count desc,m.media_type;
