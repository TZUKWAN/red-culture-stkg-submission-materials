select observed_time_status,frame_status,count(*) event_count,
       sum(occurrence_time_fact_count) occurrence_time_fact_count,
       sum(trusted_time_fact_count) trusted_time_fact_count,
       sum(event_location_fact_count) event_location_fact_count
from research_event_frames
group by observed_time_status,frame_status
order by observed_time_status,frame_status;
