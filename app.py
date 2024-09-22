# app.py

from io import BytesIO
import os
import logging
from flask import Flask, abort, render_template, send_file
import pyodbc
from pymongo import MongoClient
from bson import Binary

# Configure logging
logging.basicConfig(level=logging.INFO)

# Initialize Flask app
app = Flask(__name__)

# Load environment variables only in development
enviroment = "prod"
if enviroment == 'develodevpment':
    from dotenv import load_dotenv
    load_dotenv()

# Classes
class Campsite:
    """
    Represents a campsite with an ID, size, and daily rate.
    """

    def __init__(self, site_id, site_size, daily_rate):
        self.site_id = site_id
        self.site_size = site_size
        self.daily_rate = daily_rate


class Customer:
    """
    Represents a customer with personal details.
    """

    def __init__(self, first_name, last_name, phone_no, address, post_code):
        self.first_name = first_name
        self.last_name = last_name
        self.phone_no = phone_no
        self.address = address
        self.post_code = post_code


class Booking:
    """
    Represents a booking made by a customer for certain campsites.
    """

    def __init__(self, booking_id, customer, campsites, booking_date, arrival_date, booking_confirmation_pdf=None):
        self.booking_id = booking_id
        self.customer = customer
        self.campsites = campsites
        self.booking_date = booking_date
        self.arrival_date = arrival_date
        self.total_price = self.calculate_total_price()
        self.booking_confirmation_pdf = booking_confirmation_pdf

    def calculate_total_price(self):
        """
        Calculates the total price for the booking.
        """
        total_price = 0
        for campsite in self.campsites:
            total_price += campsite.daily_rate * 7
        return total_price


# Database connection functions for SQL Server and MongoDB
def head_office_db_connection():
    """
    Establishes a connection to the head office SQL Server database.

    Returns:
        pyodbc.Connection: The database connection object.
    """
    try:
        # Database connection details
        driver = os.environ.get('DRIVER')
        server = os.environ.get('SERVER')
        database = os.environ.get('DATABASE')
        username = os.environ.get('DB_USERNAME')
        password = os.environ.get('DB_PASSWORD')

        if not all([driver, server, database, username, password]):
            raise ValueError("Database connection environment variables are not fully set.")

        # Establish database connection and return it
        connection = pyodbc.connect(
            f"DRIVER={driver};"
            f"SERVER=tcp:{server},1433;"
            f"DATABASE={database};"
            f"UID={username};"
            f"PWD={password};"
            f"Encrypt=yes;"
            f"TrustServerCertificate=no;"
            f"Connection Timeout=30;"
        )
        return connection
    except Exception as error:
        logging.error(f"Error connecting to the head office database: {error}")
        return None


def campground_mongo_db_connection():
    """
    Establishes a connection to the campground MongoDB database.

    Returns:
        MongoClient: The MongoDB client object, or None if connection fails.
    """
    try:
        CONNECTION_STRING = os.environ.get('CONNECTION_STRING')
        if not CONNECTION_STRING:
            raise ValueError("CONNECTION_STRING environment variable not set.")
        client = MongoClient(CONNECTION_STRING, serverSelectionTimeoutMS=5000)
        # Verify connection
        client.admin.command('ping')
        return client
    except Exception as e:
        logging.error(f"Error connecting to the campgrounds MongoDB database: {e}")
        return None


@app.route('/')
def bookings():
    try:
        client = campground_mongo_db_connection()
        if client is None:
            logging.error("MongoDB connection failed.")
            return render_template('error.html', message="Unable to connect to the database."), 500

        db = client["campground"]
        booking_collection = db["booking"]

        bookings_cursor = booking_collection.find({}).sort("booking_date", 1)

        bookings = [
            Booking(
                booking_id=booking["booking_id"],
                customer=Customer(
                    first_name=booking["customer"]["first_name"],
                    last_name=booking["customer"]["last_name"],
                    phone_no=booking["customer"]["phone_no"],
                    address=booking["customer"]["address"],
                    post_code=booking["customer"]["post_code"],
                ),
                campsites=[
                    Campsite(
                        site_id=campsite["site_id"],
                        site_size=campsite["site_size"],
                        daily_rate=campsite["daily_rate"],
                    )
                    for campsite in booking["campsites"]
                ],
                booking_date=booking["booking_date"],
                arrival_date=booking["arrival_date"],
                booking_confirmation_pdf=Binary(booking["booking_confirmation_pdf"])
            )
            for booking in bookings_cursor
        ]

        return render_template('bookings-dashboard.html', bookings=bookings)
    except Exception as error:
        logging.error(f"Error fetching bookings: {error}")
        return render_template('error.html', message="An error occurred while fetching bookings."), 500
    finally:
        if client:
            client.close()


@app.route('/summaries')
def summaries():
    """
    Fetches summaries from the SQL database and renders them in a template.
    """
    try:
        connection = head_office_db_connection()
        if connection is None:
            logging.error("SQL Server connection failed.")
            return render_template('error.html', message="Unable to connect to the database."), 500

        cursor = connection.cursor()

        # Fetch summaries from the database
        cursor.execute("""
            SELECT campground_id, summary_date, total_sales, total_bookings
            FROM camping.summary
            WHERE campground_id = 1167560
            ORDER BY summary_date
        """)
        summaries = cursor.fetchall()

        # Close the connection
        cursor.close()
        connection.close()

        return render_template('summaries-dashboard.html', summaries=summaries)
    except Exception as e:
        logging.error(f"Error fetching summaries: {e}")
        return render_template('error.html', message="An error occurred while fetching summaries."), 500


@app.route('/booking-confirmation/booking-id:<int:booking_id>')
def booking_confirmation_pdfs(booking_id):
    """
    Serves the booking PDF for the given booking ID.
    """
    try:
        client = campground_mongo_db_connection()
        if client is None:
            logging.error("MongoDB connection failed.")
            return render_template('error.html', message="Unable to connect to the database."), 500

        db = client["campground"]
        booking_collection = db["booking"]

        # Find the booking with the given booking_id
        booking = booking_collection.find_one({"booking_id": booking_id})

        if not booking or "booking_confirmation_pdf" not in booking:
            abort(404, description="Booking or PDF not found.")

        # Get the PDF data from the booking that is stored as binary data
        pdf_bytes = booking["booking_confirmation_pdf"]

        # Return the PDF as a response
        return send_file(
            BytesIO(pdf_bytes),
            mimetype='application/pdf',
            download_name=f'booking_{booking_id}.pdf'
        )
    except Exception as e:
        logging.error(f"Error fetching PDF for booking ID {booking_id}: {e}")
        return render_template('error.html', message="An error occurred while fetching the PDF."), 500
    finally:
        if client:
            client.close()


if __name__ == "__main__":
    try:
        app.run()
    except Exception as e:
        logging.error(f"Error in main execution: {e}")
