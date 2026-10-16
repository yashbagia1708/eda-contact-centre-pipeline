SELECT brand, contact_reason, contacts, share_of_contacts, fcr_contacts, repeat_contacts, fcr_rate, volume_rank
FROM vw_contact_reason_summary WHERE reporting_month = :month ORDER BY brand, volume_rank
