def convert_to_fahrenheit(temp_in_cel):
    return int(round((temp_in_cel * (9 / 5)) + 32, 0))

def convert_to_mph(kmph):
    return int(round(kmph / 1.609344, 0))

def convert_to_inches(cm):
    return int(round(cm * 0.3937, 0))

def convert_to_celcius(temp_in_fah):
    return int(round((temp_in_fah -32 ) * (5 / 9) , 0))

def convert_to_kmph(mph):
    return int(round(mph * 1.609344, 0))

def convert_to_cm(inches):
    return int(round(inches / 0.3937, 0))