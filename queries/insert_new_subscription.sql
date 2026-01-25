INSERT INTO subscription_tracker_list(
    user_email,
    subscription_name,
    subscription_period,
    subscription_start_date
)
VALUES(%s, %s, %s, %s)