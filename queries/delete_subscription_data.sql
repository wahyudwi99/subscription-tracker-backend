UPDATE subscription_tracker_list
SET deleted_at = '@DELETED_AT'
WHERE user_email = '@USER_EMAIL'
    AND subscription_name = '@SUBSCRIPTION_NAME'
    AND deleted_at IS NULL