INSERT INTO subscription_tracker_list(
    user_id,
    user_email,
    subscription_name,
    subscription_period,
    subscription_start_date,
    subscription_end_date
)
VALUES(
    (SELECT id FROM subscription_tracker_user usr WHERE usr.email = %s),
    %s,
    %s,
    %s,
    %s,
    %s
)