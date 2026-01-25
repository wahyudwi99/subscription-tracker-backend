SELECT
    user_email,
    subscription_name,
    subscription_period,
    subscription_start_date
FROM subscription_tracker_list
WHERE user_email = '@USER_EMAIL'
    AND deleted_at IS NULL