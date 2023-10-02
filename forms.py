from flask_wtf import FlaskForm
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from wtforms import SelectField, DecimalField, SubmitField, FloatField, SubmitField, RadioField
from wtforms.validators import DataRequired, NumberRange
import json

with open("assets.json", "r") as f:
    assets = json.load(f)

# Convert assets list to the format needed for SelectField choices
asset_choices = [(asset, asset) for asset in assets]

class User(UserMixin):
    def __init__(self, id, username, assets, borrowed_assets):
        self.id = id
        self.username = username
        self.assets = assets
        self.borrowed_assets = borrowed_assets  

    def get_borrowed_assets(self):
        return self.borrowed_assets

class BorrowForm(FlaskForm):
    asset_type = SelectField('Asset Type', choices=asset_choices, validators=[DataRequired()])
    amount = DecimalField('Amount', validators=[DataRequired(), NumberRange(min=0)])
    submit = SubmitField('Borrow')

class WithdrawForm(FlaskForm):
    asset_type = SelectField('Asset Type', choices=asset_choices, validators=[DataRequired()])
    amount = DecimalField('Amount', validators=[DataRequired(), NumberRange(min=0)])
    submit = SubmitField('Withdraw')

class PaybackForm(FlaskForm):
    asset_type = SelectField('Asset Type', choices=asset_choices, validators=[DataRequired()])
    amount = DecimalField('Amount', validators=[DataRequired(), NumberRange(min=0)])
    submit = SubmitField('Payback')

class SwapForm(FlaskForm):
    amount = FloatField('Amount', validators=[DataRequired(), NumberRange(min=1)])
    side = RadioField('Operation', choices=[('buy','Buy TST'),('sell','Sell TST')], default='buy', validators=[DataRequired()])
    submit = SubmitField('Execute Swap')
