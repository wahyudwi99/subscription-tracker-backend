import os
import re
import jwt
import pytz
import psycopg2
import requests
import warnings
import pandas as pd
from datetime import datetime, timedelta, timezone
from dateutil.relativedelta import relativedelta

# Define global variables
QUERY_DIR_PATH="./queries"
JWT_SECRET_KEY=os.getenv("JWT_SECRET_KEY")
JWT_ALGORITHM=os.getenv("JWT_ALGORITHM")


def postgresql_connect():
    """
    Connect to postgresql database
    """
    database_client = psycopg2.connect(
        database=os.getenv("DB_NAME"),
        user=os.getenv("DB_USERNAME"),
        password=os.getenv("DB_PASSWORD"),
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT")
    )

    return database_client


def create_jwt(data: dict):
    """
    Create JWT token for cookie session
    """
    data["exp"] = datetime.utcnow() + timedelta(hours=4)
    token = jwt.encode(data, JWT_SECRET_KEY, JWT_ALGORITHM)

    return token


def decode_jwt(token: str):
    """
    Decode JWT token which is retrieved from client
    """
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        return {"error": "Token expired"}
    except jwt.InvalidTokenError:
        return {"error": "Invalid token"}
    

def insert_new_user(json_data):
    """
    Insert new user after signing up
    """
    connection = postgresql_connect()
    cursor = connection.cursor()

    created_at = datetime.now(pytz.timezone("UTC")).strftime("%Y-%m-%d")

    with open("./queries/insert_new_user.sql", "r") as openfile:
        query_file = openfile.read()

    values = (
        json_data["name"],
        json_data["email"],
        json_data["address"],
        json_data["phone_number"],
        created_at
    )
    cursor.execute(query_file, values)
    connection.commit()

    cursor.close()
    connection.close()


def insert_payment(payment_data: dict):
    """
    Insert payments
    """
    connection = postgresql_connect()
    cursor = connection.cursor()

    with open(f"{QUERY_DIR_PATH}/insert_payment.sql", "r") as openfile:
        query_file = openfile.read()

    values = (
        payment_data["user_id"],
        payment_data["user_email"],
        payment_data["amount"],
        payment_data["total_balance"],
        payment_data["balance_duration_days"],
        payment_data["plan"],
        payment_data["payment_status"],
        payment_data["payment_id"],
        datetime.now(pytz.timezone("UTC")).strftime("%Y-%m-%d %H:%M:%S")
    )
    cursor.execute(query_file, values)
    connection.commit()

    cursor.close()
    connection.close()

    print("Successfully inserted payment data !")


def get_in_progress_payment(user_email: str):
    warnings.filterwarnings("ignore")
    connection = postgresql_connect()
    with open(f"{QUERY_DIR_PATH}/get_in_progress_payment.sql", "r") as openfile:
        query_file = openfile.read()
        query_file = query_file.replace("@EMAIL", str(user_email))
    
    df = pd.read_sql_query(query_file, connection)
    if df.values.tolist():
        payment_token = df["payment_id"].values[0]
    else:
        payment_token = None

    connection.close()

    return payment_token



def update_payment(payment_id: str,
                   payment_status: str):
    connection = postgresql_connect()
    cursor = connection.cursor()

    with open(f"{QUERY_DIR_PATH}/update_payment.sql", "r") as openfile:
        query_file = openfile.read()
        query_file = query_file.replace("@PAYMENT_ID", str(payment_id))
        query_file = query_file.replace("@PAYMENT_STATUS", str(payment_status))
        query_file = query_file.replace("@UPDATED_AT", datetime.now(pytz.timezone('UTC')).strftime("%Y-%m-%d %H:%M:%S"))
    
    cursor.execute(query_file, connection)
    connection.commit()

    cursor.close()
    connection.close()


def get_paypal_access_token():
    warnings.filterwarnings("ignore")
    response = requests.post(
        url=f"{os.getenv('PAYPAL_BASE_URL')}/v1/oauth2/token",
        data={"grant_type": "client_credentials"},
        auth=(os.getenv("PAYPAL_CLIENT_ID"), os.getenv("PAYPAL_CLIENT_SECRET"))
    )
    if response.status_code == 200:
        access_token = response.json()["access_token"]
    else:
        access_token = None

    return access_token


def get_user_data(email: str):
    warnings.filterwarnings("ignore")
    connection = postgresql_connect()
    with open(f"{QUERY_DIR_PATH}/get_user_data.sql", "r") as openfile:
        query_file = openfile.read()
        query_file = query_file.replace("@EMAIL", email)
    
    df_user = pd.read_sql_query(query_file, connection)

    data = df_user.to_json(orient="records")

    connection.close()

    return data


def get_subs_data(user_email: str):
    warnings.filterwarnings("ignore")
    connection = postgresql_connect()
    with open(f"{QUERY_DIR_PATH}/get_list_subscription.sql", "r") as openfile:
        query_file = openfile.read()
        query_file = query_file.replace("@USER_EMAIL", str(user_email))

    df_user_data = pd.read_sql_query(query_file, connection)
    if df_user_data.values.tolist():
        df_user_data["subscription_start_date"] = df_user_data["subscription_start_date"].dt.strftime("%d %b %Y")
        df_user_data["subscription_end_date"] = df_user_data["subscription_end_date"].dt.strftime("%d %b %Y")
    list_subscription_data = df_user_data.to_dict(orient="records")

    subscription_data = {
        "data": {
            "user_email": user_email,
            "list_data": list_subscription_data
        }
    }

    connection.close()

    return subscription_data


def insert_new_subscription_data(data: dict):
    connection = postgresql_connect()
    cursor = connection.cursor()
    
    with open(f"{QUERY_DIR_PATH}/insert_new_subscription.sql", "r") as openfile:
        query_file = openfile.read()

    # Set subscription end date
    subs_period_int = int(re.sub(r"\smonth", "", data["subscription_period"]))
    subs_end_date = datetime.strptime(data["subscription_start_date"], "%Y-%m-%d") + relativedelta(months=subs_period_int)
    subs_end_date_str = subs_end_date.strftime("%Y-%m-%d %H:%M:%S")

    values = (
       data["user_email"],
       data["user_email"],
       data["subscription_name"],
       data["subscription_period"],
       data["subscription_start_date"],
       subs_end_date_str
    )

    cursor.execute(query_file, values)
    connection.commit()

    cursor.close()
    connection.close()


def delete_subscription_data(data: dict):
    current_timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    connection = postgresql_connect()
    cursor = connection.cursor()
    with open(f"{QUERY_DIR_PATH}/delete_subscription_data.sql", "r") as openfile:
        query_file = openfile.read()
        query_file = query_file.replace("@USER_EMAIL", str(data["email"]))
        query_file = query_file.replace("@SUBSCRIPTION_NAME", str(data["deleted_subs_name"]))
        query_file = query_file.replace("@DELETED_AT", str(current_timestamp))

    cursor.execute(query_file)
    connection.commit()

    cursor.close()
    connection.close()
