import os
import time
import httpx
import asyncio
import traceback
from pydantic import BaseModel
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from module import (create_jwt,
                    decode_jwt,
                    insert_new_user,
                    insert_payment,
                    get_paypal_access_token,
                    get_in_progress_payment,
                    update_payment,
                    get_subs_data,
                    insert_new_subscription_data,
                    delete_subscription_data)
from dotenv import load_dotenv
load_dotenv("./.env")


# Define global variables from environment
CLIENT_ID = os.getenv("GOOGLE_OAUTH_CLIENT_ID")
CLIENT_SECRET = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET")
REDIRECT_URI = f"{os.getenv('ADMIN_ENDPOINT_BASE_URL')}/auth/google/callback"
BACKEND_API_SECRET_KEY = os.getenv("BACKEND_API_SECRET_KEY")
WEBSITE_URL=os.getenv("WEBSITE_URL")
COOKIE_SECURE_STATE=True if str(os.getenv("COOKIE_SECURE_STATE")) == "True" else False
COOKIE_SAMESITE=str(os.getenv("COOKIE_SAMESITE"))


app = FastAPI()


app.add_middleware(
    CORSMiddleware,
    allow_origins=[WEBSITE_URL],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

class UpdateUserData(BaseModel):
    id: int
    name: str
    email: str
    address: str
    phone_number: str

class PaymentData(BaseModel):
    user_email: str
    amount: float
    total_balance: int
    balance_duration_days: int
    plan: str


thread_executors = ThreadPoolExecutor(
    max_workers=int(os.getenv("THREAD_NUMBERS"))
)


@app.get("/test-api")
async def testing_api():
    return "Testing API was successful !"


@app.post("/create-paypal-payment")
async def paypal_payment(payment_data: dict,
                   credentials: HTTPAuthorizationCredentials = Depends(HTTPBearer())):
    token_bearer = credentials.credentials
    if str(token_bearer) != BACKEND_API_SECRET_KEY:
        raise HTTPException(status_code=403, detail="Authorization was failed !")

    # Updating in progress payment
    try:
        in_progress_payment_token = await asyncio.to_thread(get_in_progress_payment, payment_data["user_email"])
        if in_progress_payment_token is not None:
            await asyncio.to_thread(update_payment, in_progress_payment_token, "Failed")
    except Exception:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Error on updating in progress payment")

    # Get access token and prepare payload data
    try:
        access_token = await asyncio.to_thread(get_paypal_access_token)
        body_payload = {
            "intent": "CAPTURE",
            "purchase_units": [
                {
                    "amount": {
                    "currency_code": "USD",
                    "value": str(payment_data['amount'])
                    }
                }
            ],
            "application_context": {
                "return_url": f"{os.getenv('ADMIN_ENDPOINT_BASE_URL')}/paypal-callback",
                "cancel_url": f"{os.getenv('ADMIN_ENDPOINT_BASE_URL')}/cancel-url",
                "landing_page": "BILLING"
            }
        }
    except Exception:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Error on getting payment access token and prepare payload data")

    # Create payment
    async with httpx.AsyncClient() as request_client:
        payment_response = await request_client.post(
            url=f"{os.getenv('PAYPAL_BASE_URL')}/v2/checkout/orders/",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {access_token}"
            },
            json=body_payload
        )
        if payment_response.status_code == 201:
            payment_response = payment_response.json()
            # Add status and payment id (order id) to payment_data
            payment_data["payment_status"] = "In Progress"
            payment_data["payment_id"] = str(payment_response["id"])
            redirect_url = [
                link_data["href"] for link_data in payment_response["links"] if link_data["rel"] == "approve"
            ]

            # Insert in progress payment data to database
            try:
                await asyncio.to_thread(insert_payment, payment_data)
            except Exception:
                traceback.print_exc()
                raise HTTPException(status_code=500, detail="Error on inserting payment data")
        else:
            redirect_url = f"{WEBSITE_URL}/error"

    json_response = {
        "payment_url": redirect_url
    }

    return json_response


@app.get("/cancel-url")
async def paypal_cancel_callback():

    return RedirectResponse(f"{WEBSITE_URL}/user-profile")


@app.get("/paypal-callback")
async def paypal_callback(token: str):
    # Get payment access token
    try:
        access_token = await asyncio.to_thread(get_paypal_access_token)
    except Exception:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Error on getting payment access token")

    capture_payment_url = f"{os.getenv('PAYPAL_BASE_URL')}/v2/checkout/orders/{token}/capture"

    async with httpx.AsyncClient() as request_client:
        response = await request_client.post(
            url=capture_payment_url,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {access_token}"
            }
        )
    try:
        if response.status_code == 201:
            await asyncio.to_thread(update_payment, token, "Paid")
            redirect_page = "user-profile"
        else:
            await asyncio.to_thread(update_payment, token, "Failed")
            redirect_page = "payment-error"
    except Exception:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Error on updating payment data")

    return RedirectResponse(f"{WEBSITE_URL}/{redirect_page}")
    


@app.get("/auth/google")
async def auth_google():
    """
    Redirect to google authentication page throuh this link below
    """
    google_auth_url = (
        "https://accounts.google.com/o/oauth2/v2/auth"
        "?response_type=code"
        f"&client_id={CLIENT_ID}"
        f"&redirect_uri={REDIRECT_URI}"
        "&scope=openid%20email%20profile"
    )

    return RedirectResponse(google_auth_url)


@app.get("/auth/google/callback")
async def google_callback(code: str = None,
                          error: str = None):
    """
    Process google authentication callback
    """
    if error:
        return RedirectResponse(url=WEBSITE_URL)

    # Get access token from authentication process
    token_url = "https://oauth2.googleapis.com/token"
    data = {
        "code": code,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "redirect_uri": REDIRECT_URI,
        "grant_type": "authorization_code",
    }
    try:
        async with httpx.AsyncClient() as request_client:
            auth_response = await request_client.post(token_url, data=data)
            token_data = auth_response.json()
            access_token = token_data.get("access_token")

            # Get user's data from available access token
            userinfo_url = "https://www.googleapis.com/oauth2/v1/userinfo"
            userinfo_res = await request_client.get(
                userinfo_url, headers={"Authorization": f"Bearer {access_token}"}
            )
            user = userinfo_res.json()

        # Create JWT token for transfering the file securely
        payload = {
            "email": user["email"],
            "name": user["name"]
        }
        jwt_token = create_jwt(payload)

        # Get user's profile data from database and redirect to specific page
        user_profile_data = await asyncio.to_thread(get_user_profile_data, user["email"])
        endpoint = "signup-form" if user_profile_data["data"] == "data is not found !" else "user-profile"

        response = RedirectResponse(url=f"{WEBSITE_URL}/{endpoint}")

        # Set cookie to the client
        response.set_cookie(
            key='cookie_session',
            value=jwt_token,
            httponly=True,
            secure=COOKIE_SECURE_STATE,
            samesite=COOKIE_SAMESITE,
            path="/",
            expires=datetime.now(timezone.utc) + timedelta(hours=4)
        )

        return response
    except Exception:
        traceback.print_exc()
        HTTPException(status_code=500, detail="Error on google callback")



@app.post("/logout")
async def logout(credentials: HTTPAuthorizationCredentials = Depends(HTTPBearer())):
    """
    This endpoint works when user clicks logout button on front-end page, then his/her
    cookie will be deleted
    """
    token_bearer = credentials.credentials
    if str(token_bearer) != BACKEND_API_SECRET_KEY:
        raise HTTPException(status_code=403, detail="Authorization was failed !")

    response = JSONResponse({"status_code": 200, "message": "successfully logout !"})
    response.delete_cookie(
        key="cookie_session",
        httponly=True,
        secure=COOKIE_SECURE_STATE,
        samesite=COOKIE_SAMESITE,
        path="/"
    )

    return response


@app.post("/insert-new-user")
async def insert_user(json_data: dict,
                      request: Request,
                      credentials: HTTPAuthorizationCredentials = Depends(HTTPBearer())):
    """
    When there is a new user signs up, this endpoint will inserts his/her data to database
    """
    token_bearer = credentials.credentials
    if str(token_bearer) != BACKEND_API_SECRET_KEY:
        raise HTTPException(status_code=403, detail="Authorization was failed !")

    try:
        jwt_token = request.cookies.get("cookie_session")
        data = decode_jwt(jwt_token)
        if "email" not in data.keys():
            redirect_url = "/login"
        else:
            json_data["email"] = data["email"]
            await asyncio.to_thread(insert_new_user, json_data)
            redirect_url = "/user-profile"

        json_data = {
            "status": 200,
            "redirect_url": redirect_url
        }

        return json_data

    except Exception:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Insert process was failed !")



@app.post("/get-subscription-data")
async def get_subscription_data(data: dict,
                                credentials: HTTPAuthorizationCredentials = Depends(HTTPBearer())):
    """
    
    """
    token_bearer = credentials.credentials
    if str(token_bearer) != BACKEND_API_SECRET_KEY:
        raise HTTPException(status_code=403, detail="Authorization was failed !")

    try:
        # token = request.cookies.get("cookie_session")
        # data = decode_jwt(token)
        # if "email" not in data.keys():
        #     return RedirectResponse(f"{WEBSITE_URL}/login")

        # Get data from database
        subscription_data = await asyncio.to_thread(get_subs_data, data["email"])
        return subscription_data
    except:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Error getting user profile data !")
    


@app.post("/add-subscription")
async def add_subscription(json_data: dict,
                           credentials: HTTPAuthorizationCredentials = Depends(HTTPBearer())):
    """
    When there is changes on user profile data, this endpoint will changes it and updates
    the database
    """
    token_bearer = credentials.credentials
    if str(token_bearer) != BACKEND_API_SECRET_KEY:
        raise HTTPException(status_code=403, detail="Authorization was failed !")

    try:
        await asyncio.to_thread(insert_new_subscription_data, json_data)
        json_result = {
            "status": 200,
            "message": "Data was successfully updated !"
        }

        return json_result
    except Exception:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Updating data was failed !")
    

@app.post("/delete-subscription")
async def delete_subscription(json_data: dict,
                              credentials: HTTPAuthorizationCredentials = Depends(HTTPBearer())):
    token_bearer = credentials.credentials
    if str(token_bearer) != BACKEND_API_SECRET_KEY:
        raise HTTPException(status_code=403, detail="Authorization was failed !")
    
    try:
        await asyncio.to_thread(delete_subscription_data, json_data)

        json_result = {
            "status": 200,
            "message": "Data was successfully deleted !"
        }

        return json_result
    except Exception:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Deleting data was failed !")